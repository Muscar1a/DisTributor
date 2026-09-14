"""Nạp và validate 3 file YAML cấu hình — fail fast lúc startup (§D, 06_architecture §1.5).

Nguyên tắc: cấu hình sai phải chết lúc deploy, không chết lúc runtime. Mọi lỗi nêu rõ
đường dẫn khóa bị sai để người sửa không phải đoán.
"""

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.gateway.app.api.limits import MAX_INPUT_TOKENS, MAX_MESSAGES

from ..core.interfaces import ModelRef, Tier

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent


class ConfigError(Exception):
    """Cấu hình không hợp lệ — chặn boot."""


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    input_per_1m_usd: float
    output_per_1m_usd: float
    quality_rank: int
    context_window: int = 128_000


@dataclass(frozen=True)
class PolicyRule:
    tier_shift: int
    order_by: str


@dataclass(frozen=True)
class TierRoute:
    primary: ModelRef
    fallbacks: tuple[ModelRef, ...]

    @property
    def all_models(self) -> tuple[ModelRef, ...]:
        return (self.primary, *self.fallbacks)


@dataclass(frozen=True)
class Config:
    """Ảnh chụp bất biến của cấu hình — đọc một lần lúc boot, không đọc lại giữa request."""

    tiers: dict[Tier, TierRoute]
    t1_max: int
    t2_max: int
    default_policy: str
    policies: dict[str, PolicyRule]
    pricing: dict[str, ModelPricing]
    premium_baseline_model: str

    ORDER_BY_VALUES = frozenset({"cost_asc", "quality_then_cost", "quality_desc"})


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Thiếu file cấu hình: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: YAML sai cú pháp — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: nội dung phải là mapping")
    return data


def _model_ref(raw: object, where: str) -> ModelRef:
    if not isinstance(raw, dict) or "model" not in raw or "provider" not in raw:
        raise ConfigError(f"{where}: cần dạng {{model: ..., provider: ...}}, nhận được {raw!r}")
    return ModelRef(model_id=str(raw["model"]), provider=str(raw["provider"]))


def load_config(config_dir: str | Path | None = None) -> Config:
    base = Path(config_dir or os.getenv("CONFIG_DIR") or DEFAULT_CONFIG_DIR)

    models_raw = _read_yaml(base / "models.yaml")
    policies_raw = _read_yaml(base / "policies.yaml")
    pricing_raw = _read_yaml(base / "pricing.yaml")

    tiers: dict[Tier, TierRoute] = {}
    for tier in Tier:
        node = (models_raw.get("tiers") or {}).get(tier.value)
        if node is None:
            raise ConfigError(f"models.yaml: thiếu tiers.{tier.value}")
        fallbacks = tuple(
            _model_ref(item, f"models.yaml: tiers.{tier.value}.fallbacks[{i}]")
            for i, item in enumerate(node.get("fallbacks") or [])
        )
        tiers[tier] = TierRoute(
            primary=_model_ref(node.get("primary"), f"models.yaml: tiers.{tier.value}.primary"),
            fallbacks=fallbacks,
        )

    thresholds = models_raw.get("thresholds") or {}
    t1_max, t2_max = int(thresholds.get("t1_max", 30)), int(thresholds.get("t2_max", 60))
    if not 0 < t1_max < t2_max <= 100:
        raise ConfigError(f"models.yaml: thresholds phải thoả 0 < t1_max < t2_max <= 100 (đang là {t1_max}, {t2_max})")

    pricing: dict[str, ModelPricing] = {}
    for model_id, node in (pricing_raw.get("models") or {}).items():
        try:
            rank = int(node["quality_rank"])
            entry = ModelPricing(
                provider=str(node["provider"]),
                input_per_1m_usd=float(node["input_per_1m_usd"]),
                output_per_1m_usd=float(node["output_per_1m_usd"]),
                quality_rank=rank,
                context_window=int(node.get("context_window", 128_000)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"pricing.yaml: models.{model_id} thiếu/sai trường — {exc}") from exc
        if not 1 <= rank <= 10:
            raise ConfigError(f"pricing.yaml: models.{model_id}.quality_rank phải trong 1..10, đang là {rank}")
        pricing[str(model_id)] = entry

    policies: dict[str, PolicyRule] = {}
    for name, node in (policies_raw.get("policies") or {}).items():
        order_by = str((node or {}).get("order_by", ""))
        if order_by not in Config.ORDER_BY_VALUES:
            raise ConfigError(
                f"policies.yaml: policies.{name}.order_by phải thuộc {sorted(Config.ORDER_BY_VALUES)}, "
                f"đang là {order_by!r}"
            )
        policies[str(name)] = PolicyRule(tier_shift=int(node.get("tier_shift", 0)), order_by=order_by)

    default_policy = str(models_raw.get("default_policy", "balanced"))
    if default_policy not in policies:
        raise ConfigError(f"models.yaml: default_policy {default_policy!r} không có trong policies.yaml")

    # Ràng buộc chéo (§D): mọi model được định tuyến phải có giá.
    missing = sorted(
        {ref.model_id for route in tiers.values() for ref in route.all_models if ref.model_id not in pricing}
    )
    if missing:
        raise ConfigError(f"models.yaml định tuyến tới model chưa có giá trong pricing.yaml: {missing}")

    baseline = str(pricing_raw.get("premium_baseline_model", ""))
    if baseline not in pricing:
        raise ConfigError(f"pricing.yaml: premium_baseline_model {baseline!r} không có trong models")

    return Config(
        tiers=tiers,
        t1_max=t1_max,
        t2_max=t2_max,
        default_policy=default_policy,
        policies=policies,
        pricing=pricing,
        premium_baseline_model=baseline,
    )


@dataclass(frozen=True)
class RoutingConfig:
    alpha: float = 0.45
    deescalate_margin: int = 15
    dwell_turns: int = 1
    max_session_escalations: int = 3
    failure_boost: int = 15
    streak_boost: int = 10
    similarity_threshold: float = 0.85
    session_routing_ttl_s: int = 7200
    router_cost_budget_pct: float = 2.0


def load_routing_config(config_dir: str | Path | None = None) -> RoutingConfig:
    base = Path(config_dir or os.getenv("CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    path = base / "routing.yaml"
    if not path.exists():
        return RoutingConfig()
    raw = _read_yaml(path)
    return RoutingConfig(**{
        f.name: type(f.default)(raw[f.name]) if f.name in raw else f.default
        for f in dataclasses.fields(RoutingConfig)
    })


@dataclass(frozen=True)
class GatewaySettings:
    use_mock_providers: bool = False
    max_input_tokens: int = MAX_INPUT_TOKENS
    max_messages: int = MAX_MESSAGES
    daily_token_budget: int = 50000
    router_timeout_ms: int = 2500
    request_timeout_s: float = 60.0
    classifier_v2_model: str = "gpt-5-nano"
    cb_error_threshold: int = 5
    cb_open_seconds: int = 300


def load_gateway_settings(config_dir: str | Path | None = None) -> GatewaySettings:
    base = Path(config_dir or os.getenv("CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    path = base / "config.yaml"
    raw = _read_yaml(path) if path.exists() else {}
    routing = raw.get("routing") or {}
    cb = raw.get("circuit_breaker") or {}

    use_mock_env = os.getenv("USE_MOCK_PROVIDERS")
    use_mock = (
        use_mock_env.lower() == "true"
        if use_mock_env is not None
        else bool(routing.get("use_mock_providers", False))
    )

    max_input = int(os.getenv("MAX_INPUT_TOKENS", str(routing.get("max_input_tokens", MAX_INPUT_TOKENS))))
    max_msg = int(os.getenv("MAX_MESSAGES", str(routing.get("max_messages", MAX_MESSAGES))))
    daily_budget = int(os.getenv("DAILY_TOKEN_BUDGET", str(routing.get("daily_token_budget", 50000))))
    router_timeout = int(os.getenv("ROUTER_TIMEOUT_MS", str(routing.get("router_timeout_ms", 2500))))
    req_timeout = float(os.getenv("REQUEST_TIMEOUT_S", str(routing.get("request_timeout_s", 60.0))))
    v2_model = str(os.getenv("CLASSIFIER_V2_MODEL", routing.get("classifier_v2_model", "gpt-5-nano")))

    cb_err = int(os.getenv("CB_ERROR_THRESHOLD", str(cb.get("error_threshold", 5))))
    cb_open = int(os.getenv("CB_OPEN_SECONDS", str(cb.get("open_seconds", 300))))

    return GatewaySettings(
        use_mock_providers=use_mock,
        max_input_tokens=max_input,
        max_messages=max_msg,
        daily_token_budget=daily_budget,
        router_timeout_ms=router_timeout,
        request_timeout_s=req_timeout,
        classifier_v2_model=v2_model,
        cb_error_threshold=cb_err,
        cb_open_seconds=cb_open,
    )
