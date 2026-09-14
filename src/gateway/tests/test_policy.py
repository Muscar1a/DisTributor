"""Unit test cho PolicyEngineV1 — đối chiếu cam kết trong contract §B.3."""

import pytest

from src.gateway.app.config.loader import (
    Config,
    ConfigError,
    ModelPricing,
    PolicyRule,
    TierRoute,
    load_config,
)
from src.gateway.app.core.interfaces import (
    ClassificationResult,
    ModelRef,
    NoCapableModelError,
    Tier,
)
from src.gateway.app.core.policy import PolicyEngineV1


def ref(model_id: str, provider: str = "google") -> ModelRef:
    return ModelRef(model_id=model_id, provider=provider)


@pytest.fixture
def config() -> Config:
    """Cấu hình rút gọn, tách khỏi file YAML thật để test không vỡ khi đổi model."""
    return Config(
        tiers={
            Tier.T1: TierRoute(ref("cheap-a", "google"), (ref("cheap-b", "groq"), ref("free-c", "mock"))),
            Tier.T2: TierRoute(ref("mid-a", "google"), (ref("mid-b", "groq"),)),
            Tier.T3: TierRoute(ref("top-a", "google"), (ref("top-b", "groq"),)),
        },
        t1_max=30,
        t2_max=60,
        default_policy="balanced",
        policies={
            "cost_first": PolicyRule(tier_shift=-10, order_by="cost_asc"),
            "balanced": PolicyRule(tier_shift=0, order_by="quality_then_cost"),
            "quality_first": PolicyRule(tier_shift=10, order_by="quality_desc"),
        },
        pricing={
            "cheap-a": ModelPricing("google", 0.1, 0.4, 3),
            "cheap-b": ModelPricing("groq", 0.6, 0.8, 5),
            "free-c": ModelPricing("mock", 0.0, 0.0, 1),
            "mid-a": ModelPricing("google", 0.3, 1.2, 6),
            "mid-b": ModelPricing("groq", 0.7, 1.0, 4),
            "top-a": ModelPricing("google", 1.25, 5.0, 9),
            "top-b": ModelPricing("groq", 0.75, 1.0, 7),
            "baseline-x": ModelPricing("openai", 2.0, 8.0, 8),
        },
        premium_baseline_model="top-a",
    )


@pytest.fixture
def engine(config) -> PolicyEngineV1:
    return PolicyEngineV1(config=config)


def result(score: int) -> ClassificationResult:
    tier = Tier.T1 if score < 30 else (Tier.T2 if score < 60 else Tier.T3)
    return ClassificationResult(score=score, tier=tier, signals=[], classifier_version="test", latency_ms=1)


def ids(plan) -> list[str]:
    return [m.model_id for m in plan.chain]


# --- Ánh xạ tier theo policy ------------------------------------------------


@pytest.mark.parametrize(
    ("score", "policy", "expected"),
    [
        (10, "balanced", Tier.T1),
        (45, "balanced", Tier.T2),
        (80, "balanced", Tier.T3),
        (35, "cost_first", Tier.T1),  # 35-10=25 -> T1
        (65, "cost_first", Tier.T2),  # 65-10=55 -> T2
        (25, "quality_first", Tier.T2),  # 25+10=35 -> T2
        (55, "quality_first", Tier.T3),  # 55+10=65 -> T3
    ],
)
def test_tier_shift_ap_len_diem_truoc_khi_anh_xa(engine, score, policy, expected):
    assert engine.select(result(score), policy=policy).tier_effective is expected


def test_diem_sau_shift_bi_kep_trong_0_100(engine):
    assert engine.select(result(0), policy="cost_first").tier_effective is Tier.T1
    assert engine.select(result(100), policy="quality_first").tier_effective is Tier.T3


def test_policy_mac_dinh_khi_khong_truyen(engine):
    assert engine.select(result(45)).policy_applied == "balanced"


def test_policy_khong_ton_tai_thi_bao_loi(engine):
    with pytest.raises(NoCapableModelError):
        engine.select(result(45), policy="khong-co-that")


# --- Thứ tự chain -----------------------------------------------------------


def test_primary_luon_dung_dau_du_policy_nao(engine):
    """US-03: admin chốt model chính — order_by chỉ sắp xếp fallback."""
    for policy in ("cost_first", "balanced", "quality_first"):
        assert ids(engine.select(result(10), policy=policy, force_tier=Tier.T1))[0] == "cheap-a"


def test_cost_asc_sap_fallback_theo_gia_tang_dan(engine):
    plan = engine.select(result(10), policy="cost_first", force_tier=Tier.T1)
    assert ids(plan) == ["cheap-a", "free-c", "cheap-b"]


def test_quality_desc_sap_fallback_theo_chat_luong(engine):
    plan = engine.select(result(10), policy="quality_first", force_tier=Tier.T1)
    assert ids(plan) == ["cheap-a", "cheap-b", "free-c"]


def test_chain_khong_bao_gio_rong(engine):
    for score in (0, 30, 60, 100):
        assert ids(engine.select(result(score)))


# --- exclude (circuit breaker) ---------------------------------------------


def test_loai_model_dang_bi_circuit_open(engine):
    plan = engine.select(result(10), force_tier=Tier.T1, exclude=frozenset({("cheap-a", "google")}))
    assert "cheap-a" not in ids(plan)
    assert ids(plan)[0] in {"cheap-b", "free-c"}


def test_tier_rong_sau_loc_thi_leo_len_tier_cao_hon(engine):
    """Không bao giờ tụt xuống tier rẻ hơn — rủi ro R1."""
    excluded = frozenset({("cheap-a", "google"), ("cheap-b", "groq"), ("free-c", "mock")})
    plan = engine.select(result(10), force_tier=Tier.T1, exclude=excluded)
    assert plan.tier_effective is Tier.T2
    assert ids(plan)[0] == "mid-a"


def test_het_sach_model_thi_raise_no_capable(engine, config):
    excluded = frozenset((ref_.model_id, ref_.provider) for route in config.tiers.values() for ref_ in route.all_models)
    with pytest.raises(NoCapableModelError):
        engine.select(result(10), exclude=excluded)


# --- Lọc theo capability ----------------------------------------------------


def test_loc_model_thieu_capability(config):
    engine = PolicyEngineV1(
        config=config,
        model_capabilities={
            "cheap-a": frozenset({"text"}),
            "cheap-b": frozenset({"text", "stream"}),
            "free-c": frozenset({"text"}),
            "mid-a": frozenset({"text", "stream"}),
            "mid-b": frozenset({"text"}),
            "top-a": frozenset({"text", "stream"}),
            "top-b": frozenset({"text"}),
        },
    )
    plan = engine.select(result(10), force_tier=Tier.T1, required_capabilities=frozenset({"text", "stream"}))
    assert ids(plan) == ["cheap-b"]


def test_model_chua_dang_ky_adapter_mac_dinh_text_only(engine):
    plan = engine.select(result(10), force_tier=Tier.T1, required_capabilities=frozenset({"text"}))
    assert ids(plan)[0] == "cheap-a"


# --- Override ---------------------------------------------------------------


def test_force_tier_bo_qua_diem_classifier(engine):
    plan = engine.select(result(95), force_tier=Tier.T1)
    assert plan.tier_effective is Tier.T1
    assert ids(plan)[0] == "cheap-a"


def test_force_model_cho_chain_mot_phan_tu(engine):
    plan = engine.select(result(10), force_model="top-b")
    assert ids(plan) == ["top-b"]
    assert plan.tier_effective is Tier.T3


def test_force_model_cho_pricing_only_baseline(engine):
    plan = engine.select(result(10), force_model="baseline-x")
    assert ids(plan) == ["baseline-x"]
    assert plan.chain[0].provider == "openai"
    assert plan.tier_effective is Tier.T1


def test_force_model_khong_ton_tai_thi_raise(engine):
    with pytest.raises(NoCapableModelError):
        engine.select(result(10), force_model="model-ma")


def test_force_model_thieu_capability_thi_raise(config):
    engine = PolicyEngineV1(config=config, model_capabilities={"top-b": frozenset({"text"})})
    with pytest.raises(NoCapableModelError):
        engine.select(result(10), force_model="top-b", required_capabilities=frozenset({"text", "stream"}))


# --- Config loader ----------------------------------------------------------


def test_nap_duoc_config_that_trong_repo():
    cfg = load_config()
    assert set(cfg.tiers) == {Tier.T1, Tier.T2, Tier.T3}
    assert cfg.default_policy in cfg.policies
    for route in cfg.tiers.values():
        for model in route.all_models:
            assert model.model_id in cfg.pricing, f"{model.model_id} thiếu giá trong pricing.yaml"


def test_thieu_file_config_thi_bao_loi_ro_rang(tmp_path):
    with pytest.raises(ConfigError, match="Thiếu file cấu hình"):
        load_config(tmp_path)
