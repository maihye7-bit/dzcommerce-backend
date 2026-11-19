"""add customer_memories

Revision ID: 5e62604ab459
Revises: 728238e41e4a
Create Date: 2026-09-29 15:47:27.901348

This migration correctly adds the customer_memories table.
The previous version incorrectly dropped ai_usage_events instead.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5e62604ab459'
down_revision: Union[str, None] = '728238e41e4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create customer_memories table with the correct schema from app/models/customer_memory.py
    op.create_table(
        "customer_memories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("memory_type", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), default=1.0, nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_memories_store_customer",
        "customer_memories",
        ["store_id", "customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_memories_type",
        "customer_memories",
        ["store_id", "memory_type"],
        unique=False,
    )
    # Check constraint for confidence range
    op.create_check_constraint(
        "ck_memory_confidence_range",
        "customer_memories",
        "confidence >= 0 AND confidence <= 1",
    )


def downgrade() -> None:
    # Drop customer_memories table
    op.drop_index("ix_customer_memories_type", table_name="customer_memories")
    op.drop_index("ix_customer_memories_store_customer", table_name="customer_memories")
    op.drop_table("customer_memories")