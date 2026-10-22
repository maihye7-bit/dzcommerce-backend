"""
CODRiskScore: Stores the risk assessment for a customer regarding Cash on Delivery.
Updated automatically after every order completion/cancellation.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CODRiskScore(Base):
    __tablename__ = "cod_risk_scores"
    __table_args__ = (
        Index("ix_cod_risk_store_customer", "store_id", "customer_id", unique=True),
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

    # Score from 0 (Low Risk/Trustworthy) to 100 (High Risk/Likely to Reject)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata for transparency
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    rejected_orders: Mapped[int] = mapped_column(Integer, default=0)
    returned_orders: Mapped[int] = mapped_column(Integer, default=0)

    last_calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
