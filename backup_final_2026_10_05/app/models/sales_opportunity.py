"""
SalesOpportunity: Tracks potential sales that didn't convert immediately.
Examples: Abandoned drafts, out-of-stock inquiries, unanswered questions.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OpportunityStatus(str, enum.Enum):
    OPEN = "open"
    FOLLOWED_UP = "followed_up"
    CONVERTED = "converted"
    CLOSED = "closed"


class OpportunityType(str, enum.Enum):
    ABANDONED_DRAFT = "abandoned_draft"
    OUT_OF_STOCK_INQUIRY = "out_of_stock_inquiry"
    PRICE_INQUIRY = "price_inquiry"
    GENERAL_INTEREST = "general_interest"


class SalesOpportunity(Base):
    __tablename__ = "sales_opportunities"
    __table_args__ = (
        Index("ix_sales_opp_store_customer", "store_id", "customer_id"),
        Index("ix_sales_opp_status", "status"),
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
    opportunity_type: Mapped[OpportunityType] = mapped_column(
        String(50), nullable=False
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        String(20), default=OpportunityStatus.OPEN, nullable=False
    )
    related_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    related_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
