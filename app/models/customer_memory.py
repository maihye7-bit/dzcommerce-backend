"""
Structured customer memory for Phase 4.
NOT free-form LLM memory. Each record is attributable to application
events or explicit customer information.
"""

import uuid
from datetime import datetime

from sqlalchemy import (CheckConstraint, DateTime, Float, ForeignKey, Index,
                        String, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomerMemory(Base):
    __tablename__ = "customer_memories"
    __table_args__ = (
        Index("ix_customer_memories_store_customer", "store_id", "customer_id"),
        Index("ix_customer_memories_type", "store_id", "memory_type"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memory_confidence_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
