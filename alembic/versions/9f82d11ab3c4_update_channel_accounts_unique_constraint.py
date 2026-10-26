"""update channel accounts unique constraint to include external account id

Revision ID: 9f82d11ab3c4
Revises: db39a7d5b0a4
Create Date: 2026-10-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f82d11ab3c4"
down_revision: Union[str, None] = "db39a7d5b0a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Deduplicate channel_accounts table prior to constraint modification
    # Keep the most recently updated (or active) record per (store_id, channel, external_account_id) tuple
    op.execute(
        sa.text("""
        DELETE FROM channel_accounts
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY store_id, channel, external_account_id
                           ORDER BY is_active DESC, updated_at DESC, created_at DESC
                       ) as rnum
                FROM channel_accounts
            ) t
            WHERE t.rnum > 1
        )
        """)
    )

    # 2. Drop the existing 1-to-1 per channel constraint
    op.drop_constraint(
        "uq_channel_account_store_channel",
        "channel_accounts",
        type_="unique"
    )

    # 3. Add the new constraint allowing multiple pages per channel per store as long as external_account_id differs
    op.create_unique_constraint(
        "uq_channel_account_store_channel_ext_id",
        "channel_accounts",
        ["store_id", "channel", "external_account_id"]
    )


def downgrade() -> None:
    # 1. Deduplicate records based on old key (store_id, channel) before restoring old strict constraint
    op.execute(
        sa.text("""
        DELETE FROM channel_accounts
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY store_id, channel
                           ORDER BY is_active DESC, updated_at DESC, created_at DESC
                       ) as rnum
                FROM channel_accounts
            ) t
            WHERE t.rnum > 1
        )
        """)
    )

    # 2. Drop the multi-account constraint
    op.drop_constraint(
        "uq_channel_account_store_channel_ext_id",
        "channel_accounts",
        type_="unique"
    )

    # 3. Restore the old constraint
    op.create_unique_constraint(
        "uq_channel_account_store_channel",
        "channel_accounts",
        ["store_id", "channel"]
    )
