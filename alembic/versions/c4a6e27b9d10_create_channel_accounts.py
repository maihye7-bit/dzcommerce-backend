"""Create channel_accounts table.

Revision ID: c4a6e27b9d10
Revises: 8923ed1eb7ed
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4a6e27b9d10"
down_revision: Union[str, None] = "8923ed1eb7ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_account_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_id",
            "channel",
            name="uq_channel_account_store_channel",
        ),
    )
    op.create_index(
        "ix_channel_accounts_external",
        "channel_accounts",
        ["channel", "external_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_accounts_external", table_name="channel_accounts")
    op.drop_table("channel_accounts")
