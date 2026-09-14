"""Unit test cho ClassifierV1Heuristic — đối chiếu trực tiếp bảng PRD §6.2.

Test khẳng định **điểm và tín hiệu** (phần PRD nói rõ ràng) hơn là tier, vì tier chỉ
là hệ quả của điểm cộng với ngưỡng trong config.

Dùng `asyncio.run` thay vì pytest-asyncio để test chạy được không cần plugin/cấu hình.
"""

import asyncio

import pytest

from src.gateway.app.core.classifier_v1 import ClassifierV1Heuristic, estimate_tokens
from src.gateway.app.core.interfaces import Message, Tier


def classify(prompt: str, *, system: str | None = None, **kwargs):
    messages = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))
    return asyncio.run(ClassifierV1Heuristic(**kwargs).classify(messages))


def points_of(result, name: str) -> int | None:
    for signal in result.signals:
        if signal.name == name:
            return signal.points
    return None


# --- Fast-path Easy ---------------------------------------------------------


@pytest.mark.parametrize("prompt", ["Chào bạn", "hello", "Cảm ơn nhé", "Thanks!"])
def test_greeting_di_fast_path_ve_t1(prompt):
    result = classify(prompt)
    assert result.score == 0
    assert result.tier is Tier.T1
    assert points_of(result, "fast_path_easy") == 0


def test_cau_ngan_khong_tin_hieu_thi_fast_path():
    result = classify("Thủ đô Việt Nam là gì")
    assert result.tier is Tier.T1
    assert points_of(result, "fast_path_easy") == 0


def test_cau_ngan_nhung_co_tin_hieu_thi_khong_fast_path():
    """PRD §6.2: fast-path chỉ áp dụng khi câu ngắn KHÔNG chứa tín hiệu nào."""
    result = classify("Viết hàm sort")
    assert points_of(result, "fast_path_easy") is None
    assert points_of(result, "code") == 22


# --- Từng tín hiệu đơn lẻ ---------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "```python\nprint(1)\n```",
        "Giúp mình debug đoạn này với",
        "Viết hàm kiểm tra số nguyên tố",
        "SELECT * FROM users where id = 3",
    ],
)
def test_tin_hieu_code_cong_22(prompt):
    assert points_of(classify(prompt), "code") == 22


@pytest.mark.parametrize(
    "prompt",
    [
        "Chứng minh bất đẳng thức Cauchy cho ba số dương",
        "Tính giúp mình 1234 * 5678 rồi cho kết quả",
        "Tìm ∫ x^2 dx trong khoảng từ 0 tới 1",
    ],
)
def test_tin_hieu_math_cong_20(prompt):
    assert points_of(classify(prompt), "math") == 20


def test_tin_hieu_multi_step_theo_tu_khoa():
    result = classify("So sánh hai phương án triển khai này giúp mình")
    assert points_of(result, "multi_step") == 15


def test_tin_hieu_multi_step_khi_co_hai_cau_hoi():
    result = classify("Cái này là gì? Và dùng trong trường hợp nào?")
    assert points_of(result, "multi_step") == 15


def test_tin_hieu_rang_buoc_output():
    result = classify("Tóm tắt tin này và trả về JSON đúng schema đã cho")
    assert points_of(result, "output_constraint") == 10


def test_tin_hieu_sang_tao_dai_can_ca_hai_dieu_kien():
    dai = classify("Viết bài luận về biến đổi khí hậu khoảng 1200 từ")
    ngan = classify("Viết bài blog ngắn 200 từ về cà phê")
    assert points_of(dai, "long_creative") == 10
    assert points_of(ngan, "long_creative") is None


# --- Độ dài và ngữ cảnh -----------------------------------------------------


def test_prompt_ngan_khong_cong_diem_do_dai():
    result = classify("Giúp mình debug đoạn code này")
    assert points_of(result, "length") is None


def test_prompt_trung_binh_cong_10():
    prompt = "Giải thích giúp mình cách hoạt động của bộ nhớ đệm trong hệ thống phân tán. " * 6
    result = classify(prompt)
    assert estimate_tokens(prompt) >= 50
    assert points_of(result, "length") == 10


def test_prompt_dai_cong_18():
    prompt = "Phân tích kiến trúc microservices và đánh đổi khi vận hành ở quy mô lớn. " * 40
    assert points_of(classify(prompt), "length") == 18


def test_ngu_canh_dai_cong_10():
    result = classify("Tóm tắt tài liệu trên", system="tài liệu rất dài " * 2000)
    assert points_of(result, "long_context") == 10


def test_system_prompt_khong_tinh_vao_do_kho():
    """System prompt dài không được kéo mọi request lên tier cao — chỉ tính long_context."""
    result = classify("Chào bạn", system="Bạn là trợ lý. " * 5)
    assert points_of(result, "fast_path_easy") == 0
    assert points_of(result, "length") is None


# --- Ánh xạ tier ------------------------------------------------------------


def test_cong_don_nhieu_tin_hieu_len_t3():
    result = classify(
        "Viết hàm Python giải phương trình bậc hai, so sánh với cách dùng numpy, và trả về JSON đúng schema mình mô tả"
    )
    assert {s.name for s in result.signals} >= {"code", "math", "multi_step", "output_constraint"}
    assert result.score >= 60
    assert result.tier is Tier.T3


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, Tier.T1), (29, Tier.T1), (30, Tier.T2), (59, Tier.T2), (60, Tier.T3), (100, Tier.T3)],
)
def test_nguong_tier_theo_prd(score, expected):
    """PRD §6.2: <30 -> T1, 30–59 -> T2, >=60 -> T3."""
    assert ClassifierV1Heuristic()._to_tier(score) is expected


def test_diem_bi_kep_trong_0_100():
    prompt = (
        "```py\ndef f():\n    return 1\n```"
        " chứng minh và so sánh, trả về JSON đúng schema, viết bài luận 2000 từ. " * 30
    )
    result = classify(prompt)
    assert 0 <= result.score <= 100


# --- Contract B.2: không bao giờ raise -------------------------------------


@pytest.mark.parametrize("prompt", ["", " ", "a", "🙂🙂🙂", "?" * 200])
def test_dau_vao_bat_thuong_khong_gay_exception(prompt):
    result = classify(prompt)
    assert result.tier in (Tier.T1, Tier.T2, Tier.T3)
    assert 0 <= result.score <= 100


def test_prompt_cuc_dai_khong_gay_exception():
    # Dựng trong thân hàm, không đưa vào parametrize: pytest nhét test id vào biến
    # môi trường PYTEST_CURRENT_TEST, mà Windows giới hạn 32.767 ký tự.
    result = classify("x" * 60_000)
    assert 0 <= result.score <= 100


def test_khong_co_message_user_van_tra_ket_qua():
    result = asyncio.run(ClassifierV1Heuristic().classify([Message(role="system", content="abc")]))
    assert result.tier in (Tier.T1, Tier.T2, Tier.T3)


def test_danh_sach_message_rong():
    assert asyncio.run(ClassifierV1Heuristic().classify([])).score >= 0


def test_qua_han_thi_tra_t2_kem_signal_loi():
    """Ngân sách âm ép mọi lần chấm đều quá hạn (ADR-009)."""
    result = classify("Viết hàm Python kiểm tra số nguyên tố", router_timeout_ms=-1)
    assert result.tier is Tier.T2
    assert result.score == 45
    assert points_of(result, "classifier_error") == 0


def test_loi_noi_bo_cung_tra_t2_khong_raise(monkeypatch):
    """Contract B.2 điều 1: mọi lỗi nội bộ đều bị nuốt, không đẩy ra ngoài."""
    monkeypatch.setattr(
        ClassifierV1Heuristic,
        "_score",
        lambda self, messages, started: (_ for _ in ()).throw(ValueError("hỏng")),
    )
    result = classify("Viết hàm Python kiểm tra số nguyên tố")
    assert result.tier is Tier.T2
    assert result.score == 45
    assert points_of(result, "classifier_error") == 0


# --- Metadata ---------------------------------------------------------------


def test_ket_qua_luon_co_version_va_latency():
    result = classify("Chào bạn")
    assert result.classifier_version == "heuristic-v1"
    assert result.latency_ms >= 0
