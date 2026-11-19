"""Corrective migration: add customer_memories table and preserve ai_usage_events

This migration fixes the faulty revision 5e62604ab459 which:
- Dropped ai_usage_events instead of preserving it
- Never created customer_memories table

This migration:
1. Creates customer_memories table with correct schema
2. Does NOT drop ai_usage_events (it was already recreated in migration 45948cf9d7b8)
3. Has proper indexes and check constraints
"""

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic
revision = "fix_customer_memories_20261119"
down_revision = "5e62604ab459"  # The faulty migration that dropped ai_usage_events
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create customer_memories table with the correct schema
    op.create_table(
        "customer_memories",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("memory_type", pg.String(length=50), nullable=False),
        sa.Column("key", pg.String(length=100), nullable=False),
        sa.Column("value", pg.String(length=500), nullable=False),
        sa.Column("confidence", pg.Float(), default=1.0, nullable=False),
        sa.Column("source", pg.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            pg.DateTime(timezone=True),
            server_default=pg.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            pg.DateTime(timezone=True),
            server_default=pg.text("now()"),
            onupdate=pg.text("now()"),
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
    op.create_check_constraint(
        "ck_memory_confidence_range",
        "customer_memories",
        "confidence >= 0 AND confidence <= 1",
    )
    # Note: ai_usage_events is NOT dropped - it was already recreated
    # in migration 45948cf9d7b8, so we preserve it here


def downgrade() -> None:
    op.drop_index("ix_customer_memories_type", table_name="customer_memories")
    op.drop_index("ix_customer_memories_store_customer", table_name="customer_memories")
    op.drop_table("customer_memories")