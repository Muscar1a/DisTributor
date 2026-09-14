from decimal import Decimal

import pytest

from src.gateway.app.core.cost import ConfigError, CostCalculator
from src.gateway.app.core.estimator import TokenEstimator
from src.gateway.app.core.interfaces import Message, Usage

# --- AC-4.1: cost = in * price_in + out * price_out, sai số 0 (tính tay từ pricing.yaml) ---


@pytest.mark.parametrize(
    "model_id,prompt,completion,expected",
    [
        # gemini-flash-lite -> gemini-3.1-flash-lite: 0.25 in / 1.50 out per 1M
        ("gemini-flash-lite", 1_000_000, 0, Decimal("0.25")),
        ("gemini-flash-lite", 0, 1_000_000, Decimal("1.50")),
        ("gemini-flash-lite", 100_000, 50_000, Decimal("0.025") + Decimal("0.075")),
        # gemini-pro: 1.25 in / 10.00 out per 1M
        ("gemini-pro", 1_000, 500, Decimal("0.00125") + Decimal("0.005")),
        # llama-3.3-70b (Groq): 0.59 in / 0.79 out
        ("llama-3.3-70b", 2_000, 1_000, Decimal("0.00118") + Decimal("0.00079")),
    ],
)
def test_cost_calculation_manual(model_id, prompt, completion, expected):
    calc = CostCalculator()
    usage = Usage(prompt_tokens=prompt, completion_tokens=completion)
    cost = calc.calc(model_id, usage)
    assert cost == expected


def test_cost_calculation_matches_formula():
    """cost = in * price_in + out * price_out với đơn vị /1M token."""
    calc = CostCalculator()
    usage = Usage(prompt_tokens=100, completion_tokens=50)
    cost = calc.calc("gemini-flash-lite", usage)
    # 100 * 0.25/1M + 50 * 1.50/1M = 0.000025 + 0.000075
    assert cost == Decimal("0.000100")


# --- Fail fast: model không có giá -> ConfigError (05_interfaces.md §B.6) ---


def test_cost_unknown_model_raises_config_error():
    calc = CostCalculator()
    usage = Usage(prompt_tokens=10, completion_tokens=5)
    with pytest.raises(ConfigError):
        calc.calc("model-khong-ton-tai", usage)


def test_cost_calculator_requires_valid_pricing_schema():
    """pricing.yaml thiếu section hoặc thiếu giá -> ConfigError ngay lúc khởi tạo."""
    with pytest.raises(ConfigError):
        CostCalculator(pricing={})
    with pytest.raises(ConfigError):
        CostCalculator(pricing={"gemini-flash-lite": {"input_per_1m_usd": 0.1}})
    with pytest.raises(ConfigError):
        CostCalculator(pricing={"gemini-flash-lite": {"input_per_1m_usd": -1, "output_per_1m_usd": 0.4}})


# --- AC-4.2: ước lượng token khi provider trả usage thiếu/sai, không crash, không cost=0 âm thầm ---


def test_estimate_usage_from_text():
    estimator = TokenEstimator()
    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello! Can you explain what is a token?"),
    ]
    completion = "Sure! A token is a small unit of text that a language model processes."
    usage = estimator.estimate_usage(messages, completion)
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0


def test_calc_with_estimated_usage_does_not_crash():
    """Khi usage thiếu, dùng estimate -> vẫn tính ra cost hợp lệ (không crash, không cost=0 âm thầm)."""
    estimator = TokenEstimator()
    calc = CostCalculator()
    messages = [Message(role="user", content="Write a python function to sort a list.")]
    completion = "def sort_list(lst):\n    return sorted(lst)"
    usage = estimator.estimate_usage(messages, completion)
    cost = calc.calc("gemini-flash-lite", usage)
    assert cost > Decimal("0")


def test_estimate_tokens_positive_for_nonempty():
    estimator = TokenEstimator()
    assert estimator.estimate_tokens("") == 0
    assert estimator.estimate_tokens("hello world") > 0
    assert estimator.estimate_tokens("A" * 32) >= 4  # ~4 chars/token heuristic
