"""Create support tables missing from the migration history.

Revision ID: 6f3a1c9d2b84
Revises: 51c7a2d9e804
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f3a1c9d2b84"
down_revision: Union[str, None] = "51c7a2d9e804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("human_handoffs"):
        op.create_table(
            "human_handoffs",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("store_id", sa.UUID(), nullable=False),
            sa.Column("conversation_id", sa.UUID(), nullable=False),
            sa.Column("customer_id", sa.UUID(), nullable=False),
            sa.Column("reason", sa.String(length=100), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("suggested_action", sa.Text(), nullable=True),
            sa.Column("resolved", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["store_id"], ["stores.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["customer_id"], ["customers.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_human_handoffs_store_id",
            "human_handoffs",
            ["store_id"],
        )
        op.create_index(
            "ix_human_handoffs_conversation_id",
            "human_handoffs",
            ["conversation_id"],
        )

    if not inspector.has_table("sales_opportunities"):
        op.create_table(
            "sales_opportunities",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("store_id", sa.UUID(), nullable=False),
            sa.Column("customer_id", sa.UUID(), nullable=False),
            sa.Column("opportunity_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("related_order_id", sa.UUID(), nullable=True),
            sa.Column("related_product_id", sa.UUID(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["store_id"], ["stores.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["customer_id"], ["customers.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["related_order_id"], ["orders.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["related_product_id"], ["products.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_sales_opp_store_customer",
            "sales_opportunities",
            ["store_id", "customer_id"],
        )
        op.create_index(
            "ix_sales_opp_status",
            "sales_opportunities",
            ["status"],
        )


def downgrade() -> None:
    # These tables may predate this compatibility migration in manually
    # provisioned databases, so dropping them here could destroy live data.
    pass
