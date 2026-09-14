from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.gateway.app.config.loader import Config
from src.gateway.app.core.circuit import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from src.gateway.app.core.interfaces import BaseAdapter, ModelRef


@dataclass(frozen=True)
class ProviderRuntimeState:
    provider: str
    status: str
    configured: bool
    available: bool
    circuit: str
    consecutive_errors: int
    open_until: str | None


@dataclass(frozen=True)
class ModelRuntimeState:
    id: str
    provider: str
    default_tier: str
    capabilities: tuple[str, ...]
    enabled: bool


@dataclass(frozen=True)
class ProviderRuntimeSnapshot:
    providers: tuple[ProviderRuntimeState, ...]
    models: tuple[ModelRuntimeState, ...]

    @property
    def available_models(self) -> int:
        return sum(model.enabled for model in self.models)

    @property
    def provider_check(self) -> str:
        if self.available_models == 0:
            return "unavailable"
        if any(provider.status != "available" for provider in self.providers):
            return "degraded"
        return "ok"


class ProviderStatusRegistry:
    """Shared source for provider health, readiness and the public model catalog."""

    def __init__(
        self,
        config: Config,
        adapters: dict[str, BaseAdapter],
        circuit: CircuitBreaker,
        *,
        probe_ttl_s: float = 30.0,
        probe_timeout_s: float = 2.0,
    ):
        self.config = config
        self.adapters = adapters
        self.circuit = circuit
        self.probe_ttl_s = probe_ttl_s
        self.probe_timeout_s = probe_timeout_s
        self._probe_results: dict[str, bool] = {}
        self._probed_at = 0.0
        self._lock = asyncio.Lock()

    async def snapshot(self) -> ProviderRuntimeSnapshot:
        await self._refresh_probes_if_stale()
        return self._build_snapshot()

    async def _refresh_probes_if_stale(self) -> None:
        now = time.monotonic()
        if self._probe_results and now - self._probed_at < self.probe_ttl_s:
            return
        async with self._lock:
            now = time.monotonic()
            if self._probe_results and now - self._probed_at < self.probe_ttl_s:
                return
            providers = sorted({pricing.provider for pricing in self.config.pricing.values()})
            results = await asyncio.gather(*(self._probe(provider) for provider in providers))
            self._probe_results = dict(zip(providers, results, strict=True))
            self._probed_at = now

    async def _probe(self, provider: str) -> bool:
        adapter = self.adapters.get(provider)
        if adapter is None:
            return False
        try:
            return bool(await asyncio.wait_for(adapter.health(), timeout=self.probe_timeout_s))
        except Exception:
            return False

    def _build_snapshot(self) -> ProviderRuntimeSnapshot:
        tiers_by_model: dict[str, str] = {}
        for tier, route in self.config.tiers.items():
            for ref in route.all_models:
                tiers_by_model.setdefault(ref.model_id, tier.value)

        models_by_provider: dict[str, list[str]] = {}
        for model_id, pricing in self.config.pricing.items():
            models_by_provider.setdefault(pricing.provider, []).append(model_id)

        providers: list[ProviderRuntimeState] = []
        model_states: list[ModelRuntimeState] = []
        circuit_snapshot = self.circuit.snapshot()

        for provider in sorted(models_by_provider):
            adapter = self.adapters.get(provider)
            probe_ok = self._probe_results.get(provider, False)
            model_ids = models_by_provider[provider]
            circuit_states = [
                circuit_snapshot.get((model_id, provider), {"state": CLOSED}) for model_id in model_ids
            ]
            aggregate_circuit = self._aggregate_circuit(state["state"] for state in circuit_states)
            enabled_models = sum(
                adapter is not None
                and model_id in adapter.models
                and probe_ok
                and self.circuit.state_of(ModelRef(model_id, provider)) != OPEN
                for model_id in model_ids
            )

            if adapter is None:
                status = "disabled"
            elif not probe_ok:
                status = "unavailable"
            elif aggregate_circuit != CLOSED:
                status = "unhealthy"
            elif enabled_models == 0:
                status = "unavailable"
            else:
                status = "available"

            retry_after = max(
                (self.circuit.retry_after_s(ModelRef(model_id, provider)) for model_id in model_ids),
                default=0.0,
            )
            open_until = datetime.now(UTC) + timedelta(seconds=retry_after) if retry_after > 0 else None
            providers.append(
                ProviderRuntimeState(
                    provider=provider,
                    status=status,
                    configured=True,
                    available=enabled_models > 0,
                    circuit=aggregate_circuit.lower(),
                    consecutive_errors=max(
                        (int(state.get("consecutive_failures", 0)) for state in circuit_states),
                        default=0,
                    ),
                    open_until=open_until.isoformat().replace("+00:00", "Z") if open_until else None,
                )
            )

            for model_id in model_ids:
                capabilities = self._model_capabilities(adapter, model_id)
                model_states.append(
                    ModelRuntimeState(
                        id=model_id,
                        provider=provider,
                        default_tier=tiers_by_model.get(model_id, "T2"),
                        capabilities=capabilities,
                        enabled=adapter is not None
                        and model_id in adapter.models
                        and probe_ok
                        and self.circuit.state_of(ModelRef(model_id, provider)) != OPEN,
                    )
                )

        return ProviderRuntimeSnapshot(providers=tuple(providers), models=tuple(model_states))

    @staticmethod
    def _aggregate_circuit(states: Any) -> str:
        values = set(states)
        if OPEN in values:
            return OPEN
        if HALF_OPEN in values:
            return HALF_OPEN
        return CLOSED

    @staticmethod
    def _model_capabilities(adapter: BaseAdapter | None, model_id: str) -> tuple[str, ...]:
        if adapter is None:
            return ()
        capabilities = adapter.model_capabilities.get(model_id, frozenset())
        return tuple(capability for capability in ("text", "stream") if capability in capabilities)
