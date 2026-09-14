import uuid
from datetime import datetime, timedelta
from decimal import Decimal
import random

from src.gateway.app.db.models import APIKey, Feedback, RequestLog, Session as SessionModel
from src.gateway.app.db.session import SessionLocal

SAMPLE_REQUESTS = [
    {
        "prompt": "Xin chào! Bạn có thể giới thiệu sơ lược về thủ đô Hà Nội không?",
        "response": "Hà Nội là thủ đô nghìn năm văn hiến của Việt Nam, nổi tiếng với Hồ Gươm, 36 phố phường cổ kính...",
        "tier": "T1",
        "score": 12,
        "policy": "balanced",
        "model": "gemini-2.0-flash-lite",
        "provider": "google",
        "signals": [{"name": "greeting", "points": -5}, {"name": "short_length", "points": 10}],
        "prompt_tokens": 28,
        "completion_tokens": 145,
        "cost_usd": Decimal("0.000045"),
        "latency_total_ms": 520,
        "latency_router_ms": 32,
        "fallback_count": 0,
        "chain_attempted": [{"model": "gemini-2.0-flash-lite", "provider": "google", "status": "ok", "error": None}],
        "feedback": {"tags": ["Nhanh", "Chính xác"], "note": "Phản hồi rất nhanh và đúng trọng tâm!"},
    },
    {
        "prompt": "Viết thuật toán QuickSort bằng Python có chú thích chi tiết độ phức tạp thuật toán O(n log n).",
        "response": "```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```",
        "tier": "T3",
        "score": 78,
        "policy": "balanced",
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "signals": [{"name": "code_request", "points": 35}, {"name": "algorithm_complexity", "points": 25}, {"name": "multi_step", "points": 18}],
        "prompt_tokens": 64,
        "completion_tokens": 420,
        "cost_usd": Decimal("0.003420"),
        "latency_total_ms": 2150,
        "latency_router_ms": 45,
        "fallback_count": 0,
        "chain_attempted": [{"model": "claude-3-5-sonnet", "provider": "anthropic", "status": "ok", "error": None}],
        "feedback": {"tags": ["Chất lượng cao", "Đầy đủ code"], "note": "Code sạch và có giải thích rõ ràng."},
    },
    {
        "prompt": "Phân tích ưu nhược điểm của kiến trúc Microservices so với Monolith trong dự án thương mại điện tử quy mô vừa.",
        "response": "Kiến trúc Microservices mang lại khả năng mở rộng độc lập và cách ly lỗi tốt, tuy nhiên làm tăng độ phức tạp vận hành và chi phí hạ tầng...",
        "tier": "T2",
        "score": 52,
        "policy": "balanced",
        "model": "gemini-2.5-flash",
        "provider": "google",
        "signals": [{"name": "analysis_task", "points": 25}, {"name": "architecture_domain", "points": 20}, {"name": "length", "points": 7}],
        "prompt_tokens": 92,
        "completion_tokens": 610,
        "cost_usd": Decimal("0.000620"),
        "latency_total_ms": 1420,
        "latency_router_ms": 38,
        "fallback_count": 1,
        "chain_attempted": [
            {"model": "llama-3.3-70b-versatile", "provider": "groq", "status": "error", "error": "rate_limit_429"},
            {"model": "gemini-2.5-flash", "provider": "google", "status": "ok", "error": None}
        ],
        "feedback": None,
    },
    {
        "prompt": "Dịch đoạn sau sang tiếng Anh: 'Công nghệ định tuyến thông minh giúp tiết kiệm chi phí gọi LLM lên tới 60%'.",
        "response": "'Smart routing technology helps save LLM API invocation costs by up to 60%.'",
        "tier": "T1",
        "score": 18,
        "policy": "cost-first",
        "model": "llama-3.1-8b-instant",
        "provider": "groq",
        "signals": [{"name": "translation_simple", "points": 15}, {"name": "short_prompt", "points": 3}],
        "prompt_tokens": 35,
        "completion_tokens": 25,
        "cost_usd": Decimal("0.000012"),
        "latency_total_ms": 340,
        "latency_router_ms": 28,
        "fallback_count": 0,
        "chain_attempted": [{"model": "llama-3.1-8b-instant", "provider": "groq", "status": "ok", "error": None}],
        "feedback": {"tags": ["Nhanh"], "note": "Dịch chuẩn xác."},
    },
    {
        "prompt": "Hãy thiết kế một hệ thống Distributed Cache với thuật toán Consistent Hashing, giải quyết bài toán Hot Partition và Thundering Herd.",
        "response": "Thiết kế hệ thống Distributed Cache cần giải quyết 3 thành phần cốt lõi: Ring Hashing với Virtual Nodes, cơ chế Mutex Lock phân tán để chống Thundering Herd...",
        "tier": "T3",
        "score": 92,
        "policy": "quality-first",
        "model": "gpt-4o",
        "provider": "openai",
        "signals": [{"name": "system_design_hard", "points": 45}, {"name": "distributed_systems", "points": 30}, {"name": "edge_cases", "points": 17}],
        "prompt_tokens": 120,
        "completion_tokens": 890,
        "cost_usd": Decimal("0.007850"),
        "latency_total_ms": 3200,
        "latency_router_ms": 52,
        "fallback_count": 0,
        "chain_attempted": [{"model": "gpt-4o", "provider": "openai", "status": "ok", "error": None}],
        "feedback": {"tags": ["Rất chi tiết", "Chính xác"], "note": "Kiến trúc đề xuất rất thực tế và chuyên sâu."},
    },
    {
        "prompt": "1 + 1 bằng mấy?",
        "response": "1 + 1 = 2.",
        "tier": "T1",
        "score": 5,
        "policy": "cost-first",
        "model": "gemini-2.0-flash-lite",
        "provider": "google",
        "signals": [{"name": "trivial_math", "points": 5}],
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "cost_usd": Decimal("0.000008"),
        "latency_total_ms": 290,
        "latency_router_ms": 21,
        "fallback_count": 0,
        "chain_attempted": [{"model": "gemini-2.0-flash-lite", "provider": "google", "status": "ok", "error": None}],
        "feedback": None,
    },
    {
        "prompt": "Tối ưu câu truy vấn PostgreSQL sau có nhiều INNER JOIN và Subquery đang bị chậm.",
        "response": "Để tối ưu câu query này, ta có thể: 1. Tạo Composite Index trên các trường WHERE/JOIN; 2. Chuyển Subquery thành CTE hoặc Window Function...",
        "tier": "T2",
        "score": 64,
        "policy": "balanced",
        "model": "llama-3.3-70b-versatile",
        "provider": "groq",
        "signals": [{"name": "database_tuning", "points": 30}, {"name": "sql_syntax", "points": 20}, {"name": "performance", "points": 14}],
        "prompt_tokens": 115,
        "completion_tokens": 480,
        "cost_usd": Decimal("0.000490"),
        "latency_total_ms": 980,
        "latency_router_ms": 41,
        "fallback_count": 0,
        "chain_attempted": [{"model": "llama-3.3-70b-versatile", "provider": "groq", "status": "ok", "error": None}],
        "feedback": {"tags": ["Hữu ích"], "note": "Query đã chạy nhanh hơn nhiều sau khi đánh index."},
    },
    {
        "prompt": "Viết bài luận 500 từ so sánh triết học Hiện sinh của Sartre và Camus về khái niệm Sự phi lý.",
        "response": "Sự phi lý (The Absurd) là trung tâm trong tư tưởng của cả Albert Camus và Jean-Paul Sartre, tuy nhiên phản ứng của họ trước sự phi lý lại phân hóa sâu sắc...",
        "tier": "T3",
        "score": 84,
        "policy": "balanced",
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "signals": [{"name": "essay_philosophical", "points": 40}, {"name": "comparative_analysis", "points": 28}, {"name": "long_form", "points": 16}],
        "prompt_tokens": 85,
        "completion_tokens": 780,
        "cost_usd": Decimal("0.005200"),
        "latency_total_ms": 2800,
        "latency_router_ms": 48,
        "fallback_count": 2,
        "chain_attempted": [
            {"model": "gpt-4o", "provider": "openai", "status": "error", "error": "timeout_60s"},
            {"model": "llama-3.3-70b-versatile", "provider": "groq", "status": "error", "error": "rate_limit_429"},
            {"model": "claude-3-5-sonnet", "provider": "anthropic", "status": "ok", "error": None}
        ],
        "feedback": {"tags": ["Sâu sắc", "Văn phong tốt"], "note": "Phân tích rất hay dù thời gian chờ hơi lâu."},
    },
    {
        "prompt": "Chuyển đổi thời gian UTC sau sang múi giờ GMT+7: 2026-08-24T04:30:00Z.",
        "response": "Thời gian tương ứng ở múi giờ GMT+7 (Việt Nam) là: 11:30:00 ngày 24/08/2026.",
        "tier": "T1",
        "score": 15,
        "policy": "balanced",
        "model": "gemini-2.0-flash-lite",
        "provider": "google",
        "signals": [{"name": "datetime_convert", "points": 15}],
        "prompt_tokens": 30,
        "completion_tokens": 40,
        "cost_usd": Decimal("0.000025"),
        "latency_total_ms": 380,
        "latency_router_ms": 24,
        "fallback_count": 0,
        "chain_attempted": [{"model": "gemini-2.0-flash-lite", "provider": "google", "status": "ok", "error": None}],
        "feedback": None,
    },
    {
        "prompt": "Tạo mẫu JSON Schema cho đối tượng UserProfile gồm id, email, fullName, roles, và metadata.",
        "response": "{\n  \"$schema\": \"http://json-schema.org/draft-07/schema#\",\n  \"title\": \"UserProfile\",\n  \"type\": \"object\",\n  \"properties\": {\n    \"id\": {\"type\": \"string\", \"format\": \"uuid\"},\n    \"email\": {\"type\": \"string\", \"format\": \"email\"},\n    \"fullName\": {\"type\": \"string\"},\n    \"roles\": {\"type\": \"array\", \"items\": {\"type\": \"string\"}},\n    \"metadata\": {\"type\": \"object\"}\n  },\n  \"required\": [\"id\", \"email\", \"fullName\"]\n}",
        "tier": "T2",
        "score": 48,
        "policy": "balanced",
        "model": "gemini-2.5-flash",
        "provider": "google",
        "signals": [{"name": "json_schema", "points": 25}, {"name": "data_modeling", "points": 18}, {"name": "structured_format", "points": 5}],
        "prompt_tokens": 58,
        "completion_tokens": 220,
        "cost_usd": Decimal("0.000280"),
        "latency_total_ms": 890,
        "latency_router_ms": 34,
        "fallback_count": 0,
        "chain_attempted": [{"model": "gemini-2.5-flash", "provider": "google", "status": "ok", "error": None}],
        "feedback": {"tags": ["Chính xác", "Đúng chuẩn"], "note": "Valid schema format."},
    }
]


def seed_data():
    db = SessionLocal()
    try:
        # Check or create default API key
        key = db.query(APIKey).first()
        if not key:
            key = APIKey(
                name="App-Demo-Client",
                key_hash="demo_hash_12345",
                key_masked="sr-****9f2c",
                rate_limit=60,
                active=True,
            )
            db.add(key)
            db.commit()
            db.refresh(key)

        now = datetime.utcnow()
        inserted_count = 0

        for i, sample in enumerate(SAMPLE_REQUESTS):
            # Stagger timestamps across the last 3 days
            req_time = now - timedelta(hours=i * 6 + random.randint(5, 45), minutes=random.randint(1, 50))
            
            # Create session for some
            sess_id = uuid.uuid4() if i % 2 == 0 else None
            if sess_id:
                sess = SessionModel(
                    id=sess_id,
                    api_key_id=key.id,
                    started_at=req_time,
                    last_activity_at=req_time + timedelta(minutes=2),
                )
                db.add(sess)

            req_id = uuid.uuid4()
            req_log = RequestLog(
                id=req_id,
                ts=req_time,
                api_key_id=key.id,
                session_id=sess_id,
                difficulty_score=sample["score"],
                tier=sample["tier"],
                policy=sample["policy"],
                signals=sample["signals"],
                classifier_version="heuristic-v1.5",
                model=sample["model"],
                provider=sample["provider"],
                chain_attempted=sample["chain_attempted"],
                prompt_tokens=sample["prompt_tokens"],
                completion_tokens=sample["completion_tokens"],
                usage_estimated=False,
                cost_usd=sample["cost_usd"],
                router_cost_usd=Decimal("0.000000"),
                latency_total_ms=sample["latency_total_ms"],
                latency_router_ms=sample["latency_router_ms"],
                status="ok",
                fallback_count=sample["fallback_count"],
                stream=False,
                messages=[{"role": "user", "content": sample["prompt"]}],
                response_content=sample["response"],
            )
            db.add(req_log)

            if sample["feedback"]:
                fb = Feedback(
                    request_id=req_id,
                    tags=sample["feedback"]["tags"],
                    note=sample["feedback"]["note"],
                    ts=req_time + timedelta(seconds=25),
                )
                db.add(fb)

            inserted_count += 1

        db.commit()
        print(f"[OK] Successfully seeded {inserted_count} sample Request Logs into database!")
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
