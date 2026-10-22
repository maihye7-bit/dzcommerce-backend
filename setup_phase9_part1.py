"""
Phase 9 Part 1 - Lost Sales & COD Models/Services
Run: python setup_phase9_part1.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 9 Part 1: Lost Sales & COD Foundation ===\n")

# ============================================================
# 1. SALES OPPORTUNITY MODEL
# ============================================================
write_file("app/models/sales_opportunity.py", '''"""
SalesOpportunity: Tracks potential sales that didn't convert immediately.
Examples: Abandoned drafts, out-of-stock inquiries, unanswered questions.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func, Index, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import enum

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    opportunity_type: Mapped[OpportunityType] = mapped_column(String(50), nullable=False)
    status: Mapped[OpportunityStatus] = mapped_column(String(20), default=OpportunityStatus.OPEN, nullable=False)
    related_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    related_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
''')

# ============================================================
# 2. COD RISK SCORE MODEL
# ============================================================
write_file("app/models/cod_risk.py", '''"""
CODRiskScore: Stores the risk assessment for a customer regarding Cash on Delivery.
Updated automatically after every order completion/cancellation.
"""
import uuid
from datetime import datetime
from sqlalchemy import Integer, Float, DateTime, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class CODRiskScore(Base):
    __tablename__ = "cod_risk_scores"
    __table_args__ = (
        Index("ix_cod_risk_store_customer", "store_id", "customer_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    
    # Score from 0 (Low Risk/Trustworthy) to 100 (High Risk/Likely to Reject)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Metadata for transparency
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    rejected_orders: Mapped[int] = mapped_column(Integer, default=0)
    returned_orders: Mapped[int] = mapped_column(Integer, default=0)
    
    last_calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
''')

# ============================================================
# 3. LOST SALES SERVICE
# ============================================================
write_file("app/services/lost_sales_service.py", '''"""
LostSalesService: Identifies and manages lost sales opportunities.
"""
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.sales_opportunity import SalesOpportunity, OpportunityType, OpportunityStatus
from app.models.order import Order, OrderStatus

def create_opportunity(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    opp_type: OpportunityType,
    related_order_id: uuid.UUID | None = None,
    related_product_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> SalesOpportunity:
    """Create a new sales opportunity record."""
    opp = SalesOpportunity(
        store_id=store_id,
        customer_id=customer_id,
        opportunity_type=opp_type,
        related_order_id=related_order_id,
        related_product_id=related_product_id,
        notes=notes,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp

def get_open_opportunities(
    db: Session,
    store_id: uuid.UUID,
    limit: int = 50,
) -> list[SalesOpportunity]:
    """Get open opportunities for a store, sorted by oldest first."""
    return (
        db.query(SalesOpportunity)
        .filter(
            SalesOpportunity.store_id == store_id,
            SalesOpportunity.status == OpportunityStatus.OPEN,
        )
        .order_by(SalesOpportunity.created_at.asc())
        .limit(limit)
        .all()
    )

def mark_as_followed_up(
    db: Session,
    opportunity_id: uuid.UUID,
) -> SalesOpportunity:
    """Mark an opportunity as followed up."""
    opp = db.query(SalesOpportunity).filter(SalesOpportunity.id == opportunity_id).first()
    if opp:
        opp.status = OpportunityStatus.FOLLOWED_UP
        opp.last_contacted_at = datetime.utcnow()
        db.commit()
        db.refresh(opp)
    return opp

def check_abandoned_drafts(
    db: Session,
    store_id: uuid.UUID,
    hours_threshold: int = 24,
) -> list[SalesOpportunity]:
    """
    Check for drafts created more than X hours ago that are still in DRAFT status.
    Creates opportunities if they don't already exist.
    """
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)
    
    abandoned_orders = (
        db.query(Order)
        .filter(
            Order.store_id == store_id,
            Order.status == OrderStatus.DRAFT,
            Order.created_at < cutoff_time,
        )
        .all()
    )

    new_opportunities = []
    for order in abandoned_orders:
        # Check if opportunity already exists for this order
        existing = (
            db.query(SalesOpportunity)
            .filter(
                SalesOpportunity.related_order_id == order.id,
                SalesOpportunity.opportunity_type == OpportunityType.ABANDONED_DRAFT,
                SalesOpportunity.status == OpportunityStatus.OPEN,
            )
            .first()
        )
        
        if not existing:
            opp = create_opportunity(
                db=db,
                store_id=store_id,
                customer_id=order.customer_id,
                opp_type=OpportunityType.ABANDONED_DRAFT,
                related_order_id=order.id,
                notes=f"Draft order {order.id} abandoned for >{hours_threshold} hours.",
            )
            new_opportunities.append(opp)
            
    return new_opportunities
''')

# ============================================================
# 4. COD INTELLIGENCE SERVICE
# ============================================================
write_file("app/services/cod_intelligence_service.py", '''"""
CODIntelligenceService: Calculates and manages COD risk scores.
"""
import uuid
from sqlalchemy.orm import Session
from app.models.cod_risk import CODRiskScore
from app.models.order import Order, OrderStatus

def calculate_risk_score(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> CODRiskScore:
    """
    Calculate COD risk score based on order history.
    Formula: (Rejected + Returned) / Total Orders * 100
    Lower is better.
    """
    orders = db.query(Order).filter(
        Order.store_id == store_id,
        Order.customer_id == customer_id,
        Order.status.in_([OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.DELIVERED])
    ).all()

    total = len(orders)
    if total == 0:
        # New customer: Neutral risk (or slightly high due to lack of data)
        risk_value = 50 
        rejected = 0
        returned = 0
    else:
        # In a real system, we'd have specific statuses for 'Rejected by Customer' or 'Returned'
        # For now, we'll assume CANCELLED after confirmation might indicate rejection
        # Or we can add specific fields later. Let's use a simple placeholder logic.
        rejected = sum(1 for o in orders if o.status == OrderStatus.CANCELLED)
        returned = 0 # Placeholder for future 'Returned' status
        
        risk_value = int((rejected + returned) / total * 100)

    # Upsert logic
    score_record = (
        db.query(CODRiskScore)
        .filter(
            CODRiskScore.store_id == store_id,
            CODRiskScore.customer_id == customer_id,
        )
        .first()
    )

    if not score_record:
        score_record = CODRiskScore(
            store_id=store_id,
            customer_id=customer_id,
            risk_score=risk_value,
            total_orders=total,
            rejected_orders=rejected,
            returned_orders=returned,
        )
        db.add(score_record)
    else:
        score_record.risk_score = risk_value
        score_record.total_orders = total
        score_record.rejected_orders = rejected
        score_record.returned_orders = returned

    db.commit()
    db.refresh(score_record)
    return score_record

def get_risk_score(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> CODRiskScore | None:
    """Get existing risk score without recalculating."""
    return (
        db.query(CODRiskScore)
        .filter(
            CODRiskScore.store_id == store_id,
            CODRiskScore.customer_id == customer_id,
        )
        .first()
    )
''')

# ============================================================
# 5. UPDATE models/__init__.py
# ============================================================
write_file("app/models/__init__.py", '''"""
Import every model here so that Base.metadata knows about all tables.
Phase 9: Lost Sales & COD Intelligence
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationStatus, MessageRole, Message
from app.models.order import Order, OrderItem, OrderStatus
from app.models.human_handoff import HumanHandoff
from app.models.customer_memory import CustomerMemory
from app.models.channel_enums import ChannelType, EventType, MessageType
from app.models.channel_identity import ChannelIdentity
from app.models.channel_account import ChannelAccount
from app.models.webhook_log import WebhookLog
from app.models.sales_opportunity import SalesOpportunity, OpportunityStatus, OpportunityType
from app.models.cod_risk import CODRiskScore

__all__ = [
    "User", "Store", "StoreUser", "StoreRole", "Product", "Inventory",
    "Customer",
    "Conversation", "ConversationStatus", "MessageRole", "Message",
    "Order", "OrderItem", "OrderStatus",
    "HumanHandoff",
    "CustomerMemory",
    "ChannelType", "EventType", "MessageType",
    "ChannelIdentity",
    "ChannelAccount",
    "WebhookLog",
    "SalesOpportunity", "OpportunityStatus", "OpportunityType",
    "CODRiskScore",
]
''')

# ============================================================
# 6. MIGRATION 0009
# ============================================================
write_file("alembic/versions/0009_lost_sales_cod.py", '''"""lost sales and cod intelligence tables
Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create sales_opportunities table
    op.create_table(
        "sales_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("related_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("related_product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sales_opp_store_customer", "sales_opportunities", ["store_id", "customer_id"])
    op.create_index("ix_sales_opp_status", "sales_opportunities", ["status"])

    # Create cod_risk_scores table
    op.create_table(
        "cod_risk_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cod_risk_store_customer", "cod_risk_scores", ["store_id", "customer_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_cod_risk_store_customer", table_name="cod_risk_scores")
    op.drop_table("cod_risk_scores")
    op.drop_index("ix_sales_opp_status", table_name="sales_opportunities")
    op.drop_index("ix_sales_opp_store_customer", table_name="sales_opportunities")
    op.drop_table("sales_opportunities")
''')

print("\n=== Part 1 Complete ===")
print("Created:")
print("  - app/models/sales_opportunity.py")
print("  - app/models/cod_risk.py")
print("  - app/services/lost_sales_service.py")
print("  - app/services/cod_intelligence_service.py")
print("  - Updated app/models/__init__.py")
print("  - alembic/versions/0009_lost_sales_cod.py")
print("\nNext: Run tests to verify no regressions")
