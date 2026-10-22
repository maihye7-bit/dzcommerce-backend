"""recreate_ai_usage_events_table

Revision ID: 45948cf9d7b8
Revises: c4a6e27b9d10
Create Date: 2026-10-08 11:10:02.974936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45948cf9d7b8'
down_revision: Union[str, None] = 'c4a6e27b9d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_store",
        "ai_usage_events",
        ["store_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_usage_provider",
        "ai_usage_events",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_ai_usage_created",
        "ai_usage_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_provider", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_store", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
