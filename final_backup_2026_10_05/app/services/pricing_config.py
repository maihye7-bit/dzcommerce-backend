"""
Provider-agnostic pricing configuration.
Prices are per 1,000,000 tokens (USD).
This can later be moved to a database table for dynamic updates.
"""

from decimal import Decimal

# Example pricing structure (subject to change by providers)
MODEL_PRICING = {
    "qwen": {
        "qwen-max": {"input": Decimal("2.00"), "output": Decimal("6.00")},
        "qwen-plus": {"input": Decimal("0.80"), "output": Decimal("2.00")},
        "qwen-turbo": {"input": Decimal("0.30"), "output": Decimal("0.60")},
    },
    "mock": {
        "mock-model": {"input": Decimal("0.00"), "output": Decimal("0.00")},
    },
}


def get_pricing(provider: str, model: str) -> dict:
    """Get pricing for a specific provider and model."""
    provider_pricing = MODEL_PRICING.get(provider, {})
    return provider_pricing.get(
        model, {"input": Decimal("0.00"), "output": Decimal("0.00")}
    )


def calculate_cost(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    """Calculate estimated cost for a request."""
    pricing = get_pricing(provider, model)
    input_cost = (Decimal(input_tokens) / Decimal("1000000")) * pricing["input"]
    output_cost = (Decimal(output_tokens) / Decimal("1000000")) * pricing["output"]
    return input_cost + output_cost
