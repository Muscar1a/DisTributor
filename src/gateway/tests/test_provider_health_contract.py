from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.chat_completions import router as chat_router
from src.gateway.app.api.health import router as health_router
from src.gateway.app.config.loader import Config, ModelPricing, PolicyRule, TierRoute
from src.gateway.app.core.circuit import CircuitBreaker
from src.gateway.app.core.interfaces import ModelRef, Tier
from src.gateway.app.core.provider_status import ProviderStatusRegistry
from src.gateway.app.db.session import SessionLocal, get_db


class HealthAdapter:
    def __init__(self, provider: str, model: str, healthy: bool = True):
        self.provider = provider
        self.models = [model]
        self.model_capabilities = {model: frozenset({"text", "stream"})}
        self.healthy = healthy
        self.health_calls = 0

    async def health(self) -> bool:
        self.health_calls += 1
        return self.healthy


def _config(providers: list[str]) -> Config:
    refs = [ModelRef(f"{provider}-model", provider) for provider in providers]
    routes = {
        Tier.T1: TierRoute(primary=refs[0], fallbacks=tuple(refs[1:])),
        Tier.T2: TierRoute(primary=refs[0], fallbacks=tuple(refs[1:])),
        Tier.T3: TierRoute(primary=refs[0], fallbacks=tuple(refs[1:])),
    }
    return Config(
        tiers=routes,
        t1_max=30,
        t2_max=60,
        default_policy="balanced",
        policies={"balanced": PolicyRule(tier_shift=0, order_by="quality_then_cost")},
        pricing={
            ref.model_id: ModelPricing(
                provider=ref.provider,
                input_per_1m_usd=0,
                output_per_1m_usd=0,
                quality_rank=1,
            )
            for ref in refs
        },
        premium_baseline_model=refs[0].model_id,
    )


def _client(config: Config, adapters: dict, circuit: CircuitBreaker, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(chat_router, prefix="/v1")
    app.state.config = config
    app.state.provider_registry = ProviderStatusRegistry(config, adapters, circuit, probe_ttl_s=60)
    def override_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("src.gateway.app.api.health.list_request_logs", lambda *_args, **_kwargs: [])
    return TestClient(app)


def _models_by_id(client: TestClient) -> dict[str, dict]:
    response = client.get("/v1/models")
    assert response.status_code == 200
    return {model["id"]: model for model in response.json()["data"]}


def test_healthy_snapshot_reconciles_health_readiness_and_models(monkeypatch):
    config = _config(["google", "openai"])
    adapters = {
        provider: HealthAdapter(provider, f"{provider}-model") for provider in ("google", "openai")
    }
    with _client(config, adapters, CircuitBreaker(), monkeypatch) as client:
        health = client.get("/healthz")
        # A later endpoint observes the same cached runtime snapshot rather
        # than independently probing and contradicting the health response.
        adapters["google"].healthy = False
        ready = client.get("/readyz")
        models = _models_by_id(client)

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert {provider["status"] for provider in health.json()["providers"]} == {"available"}
    assert ready.status_code == 200
    assert ready.json()["checks"]["providers"] == "ok"
    assert all(model["enabled"] for model in models.values())
    assert all(adapter.health_calls == 1 for adapter in adapters.values())


def test_degraded_snapshot_distinguishes_all_provider_states(monkeypatch):
    providers = ["disabled", "healthy", "offline", "open"]
    config = _config(providers)
    adapters = {
        "healthy": HealthAdapter("healthy", "healthy-model"),
        "offline": HealthAdapter("offline", "offline-model", healthy=False),
        "open": HealthAdapter("open", "open-model"),
    }
    circuit = CircuitBreaker(failure_threshold=1)
    circuit.record_error(ModelRef("open-model", "open"))

    with _client(config, adapters, circuit, monkeypatch) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        models = _models_by_id(client)

    status_by_provider = {provider["provider"]: provider for provider in health.json()["providers"]}
    assert health.json()["status"] == "degraded"
    assert status_by_provider["disabled"]["status"] == "disabled"
    assert status_by_provider["offline"]["status"] == "unavailable"
    assert status_by_provider["open"]["status"] == "unhealthy"
    assert status_by_provider["open"]["circuit"] == "open"
    assert status_by_provider["healthy"]["status"] == "available"
    assert ready.status_code == 200
    assert ready.json()["checks"]["providers"] == "degraded"
    assert models["healthy-model"]["enabled"] is True
    assert models["disabled-model"]["capabilities"] == []
    assert all(models[f"{provider}-model"]["enabled"] is False for provider in ("disabled", "offline", "open"))


def test_all_providers_down_makes_readiness_fail_and_disables_models(monkeypatch):
    config = _config(["disabled", "offline"])
    adapters = {"offline": HealthAdapter("offline", "offline-model", healthy=False)}

    with _client(config, adapters, CircuitBreaker(), monkeypatch) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        models = _models_by_id(client)

    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "config": "ok", "providers": "unavailable"},
    }
    assert all(model["enabled"] is False for model in models.values())
