from decimal import Decimal

from src.gateway.app.core.interfaces import Usage


class ConfigError(Exception):
    """Cấu hình pricing không hợp lệ hoặc model không có giá trong pricing.yaml."""


class CostCalculator:
    """Tính chi phí mỗi request từ pricing.yaml (contract B.6, AC-4.1).

    - `calc(model_id, usage)` -> cost = prompt·in_price + completion·out_price, chia 1.000.000.
    - Model không có giá -> `ConfigError` (fail fast, không trả cost=0 âm thầm).
    """

    def __init__(self, pricing: dict | None = None):
        self._pricing = self._normalize(pricing if pricing is not None else self._load_pricing())

    @staticmethod
    def _load_pricing() -> dict:
        """Đọc pricing.yaml; dùng khi pricing không được truyền vào (vd: trong tests)."""
        import os

        import yaml

        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
        yaml_path = os.path.join(config_dir, "pricing.yaml")
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        pricing = data.get("models", {})
        if not isinstance(pricing, dict) or not pricing:
            raise ConfigError("pricing.yaml thiếu section `models` hoặc rỗng")
        return pricing

    @staticmethod
    def _normalize(pricing: dict) -> dict[str, tuple[Decimal, Decimal]]:
        """Validate schema pricing: mỗi model phải có input/output >= 0. Fail fast."""
        if not isinstance(pricing, dict) or not pricing:
            raise ConfigError("pricing rỗng hoặc không hợp lệ")
        normalized: dict[str, tuple[Decimal, Decimal]] = {}
        for model_id, entry in pricing.items():
            if not isinstance(entry, dict):
                raise ConfigError(f"model '{model_id}' thiếu cấu hình giá")
            try:
                price_in = Decimal(str(entry["input_per_1m_usd"]))
                price_out = Decimal(str(entry["output_per_1m_usd"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(f"model '{model_id}' thiếu input_per_1m_usd/output_per_1m_usd") from exc
            if price_in < 0 or price_out < 0:
                raise ConfigError(f"model '{model_id}' có giá âm")
            normalized[model_id] = (price_in, price_out)
        return normalized

    def calc(self, model_id: str, usage: Usage) -> Decimal:
        """cost = in·giá_in + out·giá_out (đơn vị USD), từ pricing.yaml. Fail fast nếu model không có giá."""
        if model_id not in self._pricing:
            raise ConfigError(f"model '{model_id}' không có giá trong pricing.yaml")
        price_in, price_out = self._pricing[model_id]
        if usage.prompt_tokens < 0 or usage.completion_tokens < 0:
            raise ConfigError(f"usage âm cho model '{model_id}'")
        cost = (Decimal(usage.prompt_tokens) * price_in + Decimal(usage.completion_tokens) * price_out) / Decimal(
            1_000_000
        )
        return cost
