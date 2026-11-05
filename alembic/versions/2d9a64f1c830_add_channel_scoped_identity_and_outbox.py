"""Add account-scoped channel identities and durable outbound deliveries.

Revision ID: 2d9a64f1c830
Revises: b7e91c6a4d20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d9a64f1c830"
down_revision: Union[str, None] = "b7e91c6a4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("channel_identities"):
        op.create_table(
            "channel_identities",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("store_id", sa.UUID(), nullable=False),
            sa.Column("customer_id", sa.UUID(), nullable=False),
            sa.Column("channel", sa.String(length=20), nullable=False),
            sa.Column("external_account_id", sa.String(length=255), nullable=True),
            sa.Column("external_user_id", sa.String(length=255), nullable=False),
            sa.Column("external_username", sa.String(length=255), nullable=True),
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
                ["store_id"], ["stores.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["customer_id"], ["customers.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "store_id",
                "channel",
                "external_account_id",
                "external_user_id",
                name="uq_channel_identity_store_channel_ext_user",
            ),
        )
    else:
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("channel_identities")
        }
        if "uq_channel_identity_store_channel_ext_user" in unique_constraints:
            op.drop_constraint(
                "uq_channel_identity_store_channel_ext_user",
                "channel_identities",
                type_="unique",
            )
        columns = {
            column["name"] for column in inspector.get_columns("channel_identities")
        }
        if "external_account_id" not in columns:
            op.add_column(
                "channel_identities",
                sa.Column("external_account_id", sa.String(length=255), nullable=True),
            )
        op.create_unique_constraint(
            "uq_channel_identity_store_channel_ext_user",
            "channel_identities",
            [
                "store_id",
                "channel",
                "external_account_id",
                "external_user_id",
            ],
        )

    existing_indexes = {
        index["name"]: index
        for index in sa.inspect(bind).get_indexes("channel_identities")
    }
    if "ix_channel_identities_customer" not in existing_indexes:
        op.create_index(
            "ix_channel_identities_customer",
            "channel_identities",
            ["store_id", "customer_id"],
        )
    if "uq_channel_identity_legacy_user" not in existing_indexes:
        op.create_index(
            "uq_channel_identity_legacy_user",
            "channel_identities",
            ["store_id", "channel", "external_user_id"],
            unique=True,
            postgresql_where=sa.text("external_account_id IS NULL"),
            sqlite_where=sa.text("external_account_id IS NULL"),
        )
    lookup_index = existing_indexes.get("ix_channel_identities_lookup")
    if lookup_index:
        op.drop_index("ix_channel_identities_lookup", table_name="channel_identities")
    op.create_index(
        "ix_channel_identities_lookup",
        "channel_identities",
        ["store_id", "channel", "external_account_id", "external_user_id"],
    )

    op.create_table(
        "outbound_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("fallback_for_id", sa.UUID(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("recipient_external_id", sa.String(length=255), nullable=False),
        sa.Column("payload_type", sa.String(length=20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("failure_kind", sa.String(length=30), nullable=True),
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
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["fallback_for_id"], ["outbound_deliveries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fallback_for_id", name="uq_outbound_deliveries_fallback_for"
        ),
    )
    op.create_index(
        "ix_outbound_deliveries_conversation_id",
        "outbound_deliveries",
        ["conversation_id"],
    )
    op.create_index(
        "ix_outbound_deliveries_due",
        "outbound_deliveries",
        ["status", "next_attempt_at", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_deliveries_due", table_name="outbound_deliveries")
    op.drop_index(
        "ix_outbound_deliveries_conversation_id",
        table_name="outbound_deliveries",
    )
    op.drop_table("outbound_deliveries")
    op.drop_index("ix_channel_identities_lookup", table_name="channel_identities")
    op.drop_index(
        "uq_channel_identity_legacy_user",
        table_name="channel_identities",
    )
    op.drop_constraint(
        "uq_channel_identity_store_channel_ext_user",
        "channel_identities",
        type_="unique",
    )
    op.drop_index(
        "ix_channel_identities_customer",
        table_name="channel_identities",
    )
    op.drop_column("channel_identities", "external_account_id")
    op.create_unique_constraint(
        "uq_channel_identity_store_channel_ext_user",
        "channel_identities",
        ["store_id", "channel", "external_user_id"],
    )
