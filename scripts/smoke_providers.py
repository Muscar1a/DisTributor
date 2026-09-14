"""Smoke test — gọi provider THẬT qua adapter (chạy 1 lần, KHÔNG nằm trong pytest).

Cách dùng:
    # .env phải có GEMINI_API_KEY và GROQ_API_KEY (đã điền)
    python scripts/smoke_providers.py

Kết quả mong đợi khi hoạt động:
    Gemini health: True
    Gemini: <content thật> | finish=stop | usage=prompt=X completion=Y (estimated=False)
    Groq health: True
    Groq: <content thật> | finish=stop | usage=prompt=X completion=Y (estimated=False)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Đảm bảo import được package `src` khi chạy từ repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Nạp .env thủ công (không phụ thuộc python-dotenv nếu chưa cài)
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


async def _probe(name: str, adapter, model_id: str) -> None:
    from src.gateway.app.core.interfaces import CompletionParams, Message

    print(f"\n=== {name} ===")
    print(f"  health() -> {await adapter.health()}")
    if not await adapter.health():
        print(f"  ⚠ {name}: health=False — kiểm tra API key / mạng")
        return
    result = await adapter.complete(
        model_id,
        [Message(role="user", content="Hello! Reply with one short sentence.")],
        CompletionParams(temperature=0),
    )
    print(f"  content      : {result.content!r}")
    print(f"  finish_reason: {result.finish_reason}")
    print(f"  usage        : prompt={result.usage.prompt_tokens} completion={result.usage.completion_tokens}")
    print(f"  usage_estimat: {result.usage_estimated}")
    print(f"  latency(ms)  : {result.provider_latency_ms}")


async def main() -> None:
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    from src.gateway.app.adapters.gemini_adapter import GeminiAdapter
    from src.gateway.app.adapters.groq_adapter import GroqAdapter

    print("ADAPTER REAL-PROVIDER SMOKE TEST")
    print(f"GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))}")
    print(f"GROQ_API_KEY  set: {bool(os.getenv('GROQ_API_KEY'))}")

    await _probe("Gemini (gemini-flash-lite)", GeminiAdapter(), "gemini-flash-lite")
    await _probe("Groq (llama-3.3-70b)", GroqAdapter(), "llama-3.3-70b")

    print("\n⚠ Nhớ đóng client (nếu adapter tự tạo) — script thoát là process kết thúc.")


if __name__ == "__main__":
    asyncio.run(main())