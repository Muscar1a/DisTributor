"""Chạy thử luồng định tuyến từ dòng lệnh — không cần API, không cần API key.

    python -m src.gateway.demo_route "Viết hàm Python kiểm tra số nguyên tố"
    python -m src.gateway.demo_route --policy cost_first "Chào bạn"
    python -m src.gateway.demo_route            # chạy bộ prompt mẫu 3 tier

In ra điểm, tín hiệu đã kích hoạt và chain model sẽ thử — tức phần "giải thích được"
(NFR-05) mà dashboard sẽ hiển thị sau này.
"""

import argparse
import asyncio
import sys

from .app.core.classifier_v1 import ClassifierV1Heuristic
from .app.core.interfaces import Message
from .app.core.policy import PolicyEngineV1

SAMPLE_PROMPTS = (
    "Chào bạn, khỏe không?",
    "Tóm tắt giúp mình email này thành 3 gạch đầu dòng",
    "Viết hàm Python giải phương trình bậc hai, so sánh với cách dùng numpy, và trả về JSON đúng schema mình mô tả",
)


def route_one(classifier, engine, prompt: str, policy: str | None) -> None:
    result = asyncio.run(classifier.classify([Message(role="user", content=prompt)]))
    plan = engine.select(result, policy=policy)

    signals = ", ".join(f"{s.name}+{s.points}" for s in result.signals) or "(không có)"
    chain = " -> ".join(f"{m.model_id}@{m.provider}" for m in plan.chain)

    print(f"\nPrompt   : {prompt}")
    print(f"Score    : {result.score}  ({result.classifier_version}, {result.latency_ms}ms)")
    print(f"Tín hiệu : {signals}")
    print(f"Tier     : {result.tier.value} -> {plan.tier_effective.value}  [policy: {plan.policy_applied}]")
    print(f"Chain    : {chain}")


def main() -> None:
    # Console Windows mặc định cp1252, không in được tiếng Việt có dấu.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Demo định tuyến SmartRoute (classifier + policy engine)")
    parser.add_argument("prompt", nargs="*", help="Prompt cần định tuyến; bỏ trống để chạy bộ mẫu")
    parser.add_argument("--policy", default=None, help="cost_first | balanced | quality_first")
    args = parser.parse_args()

    classifier = ClassifierV1Heuristic()
    engine = PolicyEngineV1()

    prompts = [" ".join(args.prompt)] if args.prompt else list(SAMPLE_PROMPTS)
    for prompt in prompts:
        route_one(classifier, engine, prompt, args.policy)
    print()


if __name__ == "__main__":
    main()
