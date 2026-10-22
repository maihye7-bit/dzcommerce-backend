"""
AIUsageEvent: Tracks LLM usage, tokens, and costs for billing and analytics.
Provider-agnostic foundation for future SaaS billing.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (DateTime, ForeignKey, Index, Integer, Numeric, String,
                        func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_store", "store_id"),
        Index("ix_ai_usage_provider", "provider"),
        Index("ix_ai_usage_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "qwen", "openai", "mock"
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Cost and latency may be unavailable for some provider responses.
    estimated_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), default=Decimal("0.00"), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
