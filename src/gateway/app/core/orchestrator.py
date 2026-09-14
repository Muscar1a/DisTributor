"""RequestOrchestrator — luồng nghiệp vụ duy nhất, owner retry/fallback.

Ghép: classify → policy.select → FallbackExecutor → CostCalculator → log (2 pha).
Chi tiết contract: 06_architecture.md §2 (module view), runtime flow A & B.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.gateway.app.core.interfaces import (
    BaseClassifier,
    BasePolicyEngine,
    ClassificationResult,
    CompletionParams,
    CompletionResult,
    Message,
    ModelRef,
    Tier,
)
from src.gateway.app.core.tier_limiter import TierRateLimiter

_TIER_DOWNGRADE: dict[Tier, Tier] = {Tier.T3: Tier.T2, Tier.T2: Tier.T1}


@dataclass
class RoutingResult:
    completion: CompletionResult
    classification: ClassificationResult
    model_used: ModelRef
    chain_attempted: list[str] = field(default_factory=list)
    fallback_count: int = 0
    cost_usd: float | None = None
    latency_total_ms: int | None = None
    latency_router_ms: int | None = None


class RequestOrchestrator:
    """Owner duy nhất của retry — adapter không retry, httpx không retry (06_arch §6)."""

    def __init__(
        self,
        classifier: BaseClassifier,
        policy_engine: BasePolicyEngine,
        fallback_executor,  # FallbackExecutor — typed loosely để tránh circular dep
        cost_calculator=None,
        repository=None,
        tier_limiter: TierRateLimiter | None = None,
    ):
        self.classifier = classifier
        self.policy_engine = policy_engine
        self.fallback_executor = fallback_executor
        self.cost_calculator = cost_calculator
        self._repo = repository
        self._tier_limiter = tier_limiter

    async def handle(
        self,
        messages: list[Message],
        params: CompletionParams,
        policy: str | None = None,
        force_model: str | None = None,
        force_tier: Tier | None = None,
        required_capabilities: frozenset[str] = frozenset({"text"}),
    ) -> RoutingResult:
        router_start = time.monotonic()

        # B.2 — classify (không bao giờ raise)
        classification = await self.classifier.classify(messages)

        # B.2b — tier rate-limit gate; downgrade thay vì từ chối
        if self._tier_limiter:
            allowed = await self._tier_limiter.consume(classification.tier.value)
            if not allowed:
                force_tier = _TIER_DOWNGRADE.get(classification.tier, force_tier)

        # B.3 — dựng chain (lọc capability + exclude circuit OPEN)
        exclude: frozenset[tuple[str, str]] = self.fallback_executor.circuit.open_set() if self.fallback_executor else frozenset()
        plan = self.policy_engine.select(
            classification,
            policy=policy,
            force_model=force_model,
            force_tier=force_tier,
            required_capabilities=required_capabilities,
            exclude=exclude,
        )

        router_ms = int((time.monotonic() - router_start) * 1000)
        total_start = time.monotonic()

        # B.4/B.5 — execute chain với fallback (owner duy nhất của retry)
        fb_result = await self.fallback_executor.execute(plan.chain, messages, params)

        total_ms = int((time.monotonic() - total_start) * 1000)

        # B.6 — tính cost
        cost_usd = None
        if self.cost_calculator and fb_result.chain_attempted:
            last_model = fb_result.chain_attempted[-1]
            try:
                cost_usd = float(self.cost_calculator.calc(last_model, fb_result.result.usage))
            except Exception:
                pass

        # model_used = ref tương ứng với model cuối trong chain_attempted
        model_used = plan.chain[0]
        if fb_result.chain_attempted:
            last = fb_result.chain_attempted[-1]
            for ref in plan.chain:
                if ref.model_id == last:
                    model_used = ref
                    break

        return RoutingResult(
            completion=fb_result.result,
            classification=classification,
            model_used=model_used,
            chain_attempted=fb_result.chain_attempted,
            fallback_count=fb_result.fallback_count,
            cost_usd=cost_usd,
            latency_total_ms=total_ms,
            latency_router_ms=router_ms,
        )
