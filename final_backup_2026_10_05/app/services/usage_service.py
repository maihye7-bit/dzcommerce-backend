"""
UsageService: Records AI usage events and calculates costs.
"""

import time
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.ai_usage_event import AIUsageEvent
from app.services.pricing_config import calculate_cost


def record_usage(
    db: Session,
    store_id: uuid.UUID,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    conversation_id: uuid.UUID | None = None,
) -> AIUsageEvent:
    """Record an AI usage event and calculate estimated cost."""
    total_tokens = input_tokens + output_tokens
    cost = calculate_cost(provider, model, input_tokens, output_tokens)

    event = AIUsageEvent(
        store_id=store_id,
        conversation_id=conversation_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost=cost,
        latency_ms=latency_ms,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
