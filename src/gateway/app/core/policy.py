"""PolicyEngineV1 — dựng chuỗi model để thử theo tier và policy (FR-11, FR-04).

Contract: `interfaces.py` §B.3. Cam kết bắt buộc giữ:
  * `chain` không rỗng và không chứa phần tử trong `exclude`;
  * mọi model trong chain đều đủ `required_capabilities`;
  * tier rỗng sau lọc -> leo lên tier cao hơn, không tụt xuống tier rẻ hơn;
  * hết model phù hợp -> raise NoCapableModelError.

Nguyên tắc leo tier (không tụt): khi tier đích không còn model dùng được, chọn tier
MẠNH hơn. Tụt xuống tier rẻ để "có còn hơn không" chính là rủi ro R1 — trả lời sai
một task khó tốn kém hơn nhiều so với trả dư tiền.
"""

from ..config.loader import Config, load_config
from .interfaces import (
    BasePolicyEngine,
    ClassificationResult,
    ModelRef,
    NoCapableModelError,
    RoutingPlan,
    Tier,
)

TIER_ORDER = (Tier.T1, Tier.T2, Tier.T3)


class PolicyEngineV1(BasePolicyEngine):
    def __init__(
        self,
        config: Config | None = None,
        model_capabilities: dict[str, frozenset[str]] | None = None,
    ) -> None:
        """`model_capabilities` do AdapterRegistry cung cấp (B.4).

        Chưa có adapter nào đăng ký -> coi mọi model chỉ có capability "text", đủ để
        chạy luồng text-only của M1.
        """
        self.config = config or load_config()
        self.model_capabilities = model_capabilities or {}

    # -- API công khai ------------------------------------------------------

    def select(
        self,
        classification: ClassificationResult,
        policy: str | None = None,
        force_model: str | None = None,
        force_tier: Tier | None = None,
        floor_tier: Tier | None = None,
        required_capabilities: frozenset[str] = frozenset({"text"}),
        exclude: frozenset[tuple[str, str]] = frozenset(),
        input_tokens: int | None = None,
    ) -> RoutingPlan:
        policy_name = policy or self.config.default_policy
        rule = self.config.policies.get(policy_name)
        if rule is None:
            raise NoCapableModelError(f"Policy không tồn tại: {policy_name!r}")

        if force_model:
            return self._forced_model_plan(force_model, policy_name, classification, force_tier, required_capabilities)

        tier = force_tier or self._shifted_tier(classification.score, rule.tier_shift)
        if floor_tier and not force_tier:
            if TIER_ORDER.index(tier) < TIER_ORDER.index(floor_tier):
                tier = floor_tier

        for candidate_tier in self._tiers_from(tier):
            chain = self._chain_for(candidate_tier, rule.order_by, required_capabilities, exclude, input_tokens)
            if chain:
                return RoutingPlan(chain=chain, tier_effective=candidate_tier, policy_applied=policy_name)

        raise NoCapableModelError(
            f"Không còn model nào đủ capability {sorted(required_capabilities)} từ tier {tier.value} trở lên"
        )

    # -- Chọn tier ----------------------------------------------------------

    def _shifted_tier(self, score: int, tier_shift: int) -> Tier:
        """Áp tier_shift lên ĐIỂM rồi mới ánh xạ tier (PRD §6.2), không dịch tier trực tiếp."""
        shifted = max(0, min(100, score + tier_shift))
        if shifted < self.config.t1_max:
            return Tier.T1
        if shifted < self.config.t2_max:
            return Tier.T2
        return Tier.T3

    def _tiers_from(self, tier: Tier) -> tuple[Tier, ...]:
        return TIER_ORDER[TIER_ORDER.index(tier) :]

    # -- Dựng chain ---------------------------------------------------------

    def _chain_for(
        self,
        tier: Tier,
        order_by: str,
        required_capabilities: frozenset[str],
        exclude: frozenset[tuple[str, str]],
        input_tokens: int | None = None,
    ) -> list[ModelRef]:
        route = self.config.tiers[tier]

        def usable(ref: ModelRef) -> bool:
            if (ref.model_id, ref.provider) in exclude:
                return False
            if not self._has_capabilities(ref, required_capabilities):
                return False
            if input_tokens is not None:
                window = self._context_window(ref)
                if window < input_tokens:
                    return False
            return True

        # `primary` là lựa chọn admin đã chốt (US-03) nên luôn đứng đầu chain; `order_by`
        # chỉ quyết định thứ tự các fallback. Nếu để order_by sắp xếp cả primary thì
        # cost_asc sẽ đẩy model 0đ (mock) lên đầu và khoá cấu hình của admin thành vô nghĩa.
        chain = [route.primary] if usable(route.primary) else []
        chain.extend(self._ordered([ref for ref in route.fallbacks if usable(ref)], order_by))
        return chain

    def _has_capabilities(self, ref: ModelRef, required: frozenset[str]) -> bool:
        declared = self.model_capabilities.get(ref.model_id)
        if declared is None:
            declared = frozenset({"text"})  # chưa có adapter đăng ký — mặc định text-only
        return required <= declared

    def _ordered(self, refs: list[ModelRef], order_by: str) -> list[ModelRef]:
        if order_by == "cost_asc":
            return sorted(refs, key=self._cost_key)
        if order_by == "quality_desc":
            return sorted(refs, key=lambda ref: -self._quality(ref))
        # quality_then_cost — chất lượng cao trước, hoà điểm thì rẻ trước
        return sorted(refs, key=lambda ref: (-self._quality(ref), self._cost_key(ref)))

    def _context_window(self, ref: ModelRef) -> int:
        entry = self.config.pricing.get(ref.model_id)
        return entry.context_window if entry else 128_000

    def _quality(self, ref: ModelRef) -> int:
        entry = self.config.pricing.get(ref.model_id)
        return entry.quality_rank if entry else 0

    def _cost_key(self, ref: ModelRef) -> float:
        """Xấp xỉ chi phí một request bằng giá input + output.

        Đủ để so sánh tương đối giữa các model; con số cost thật của từng request do
        CostCalculator tính từ usage có thật (B.6).
        """
        entry = self.config.pricing.get(ref.model_id)
        if entry is None:
            return float("inf")
        return entry.input_per_1m_usd + entry.output_per_1m_usd

    # -- force_model --------------------------------------------------------

    def _forced_model_plan(
        self,
        force_model: str,
        policy_name: str,
        classification: ClassificationResult,
        force_tier: Tier | None,
        required_capabilities: frozenset[str],
    ) -> RoutingPlan:
        for tier in TIER_ORDER:
            for ref in self.config.tiers[tier].all_models:
                if ref.model_id != force_model:
                    continue
                if not self._has_capabilities(ref, required_capabilities):
                    raise NoCapableModelError(
                        f"force_model {force_model!r} không đủ capability {sorted(required_capabilities)}"
                    )
                return RoutingPlan(
                    chain=[ref],
                    tier_effective=force_tier or tier,
                    policy_applied=policy_name,
                )
        pricing = self.config.pricing.get(force_model)
        if pricing is not None:
            ref = ModelRef(model_id=force_model, provider=pricing.provider)
            if not self._has_capabilities(ref, required_capabilities):
                raise NoCapableModelError(
                    f"force_model {force_model!r} không đủ capability {sorted(required_capabilities)}"
                )
            return RoutingPlan(
                chain=[ref],
                tier_effective=force_tier or classification.tier,
                policy_applied=policy_name,
            )
        raise NoCapableModelError(f"force_model {force_model!r} không có trong pricing.yaml")
