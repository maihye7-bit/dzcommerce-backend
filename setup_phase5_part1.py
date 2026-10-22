"""
Phase 5 Setup Script - Order Workflow
Run: python setup_phase5.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 5: Order Workflow Setup ===\n")

# ============================================================
# 1. UPDATE MODELS: Expand OrderStatus enum
# ============================================================
write_file("app/models/order.py", '''"""
Order and OrderItem models for Phase 3/5.
Orders start as DRAFT and move through a controlled state machine.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    String, Text, Numeric, Integer, DateTime, ForeignKey,
    Enum, func, Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrderStatus(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_store_id", "store_id"),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status",
             values_callable=lambda e: [m.value for m in e]),
        default=OrderStatus.DRAFT, nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="DZD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_price_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
''')

# ============================================================
# 2. MIGRATION: 0005_order_workflow.py
# ============================================================
write_file("alembic/versions/0005_order_workflow.py", '''"""order workflow: expand order_status enum
Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new statuses to order_status enum
    conn = op.get_bind()
    
    # Drop the default first
    conn.execute("""
        ALTER TABLE orders ALTER COLUMN status DROP DEFAULT
    """)
    
    # Add new enum values
    for status in ["processing", "shipped", "delivered"]:
        conn.execute(f"""
            ALTER TYPE order_status ADD VALUE IF NOT EXISTS '{status}'
        """)
    
    # Set default back to draft
    conn.execute("""
        ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'draft'
    """)


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values easily
    # In production, you'd need to recreate the enum type
    # For now, we'll just leave the new values (they won't be used)
    pass
''')

print("\n=== Part 1 Complete ===")
print("Next: Creating OrderService...")
