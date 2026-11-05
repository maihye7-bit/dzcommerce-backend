"""Encrypt persisted StoreMetaToken values and allow ciphertext length.

Revision ID: 51c7a2d9e804
Revises: 2d9a64f1c830
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.services.meta_token_security import (
    TOKEN_PREFIX,
    decrypt_meta_token,
    encrypt_meta_token,
)


revision: str = "51c7a2d9e804"
down_revision: Union[str, None] = "2d9a64f1c830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_page = bind.execute(
        sa.text(
            """
            SELECT external_account_id
            FROM channel_accounts
            WHERE channel = 'facebook'
            GROUP BY external_account_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate_page is not None:
        raise RuntimeError(
            "Duplicate Facebook Page links exist; resolve them before upgrading."
        )

    op.alter_column(
        "store_meta_tokens",
        "access_token",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    rows = bind.execute(
        sa.text("SELECT id, access_token FROM store_meta_tokens")
    ).all()
    for row in rows:
        if not row.access_token.startswith(TOKEN_PREFIX):
            bind.execute(
                sa.text(
                    "UPDATE store_meta_tokens SET access_token = :token WHERE id = :id"
                ),
                {"token": encrypt_meta_token(row.access_token), "id": row.id},
            )
    op.create_index(
        "uq_channel_accounts_facebook_external",
        "channel_accounts",
        ["external_account_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'facebook'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, access_token FROM store_meta_tokens")
    ).all()
    for row in rows:
        token = decrypt_meta_token(row.access_token)
        if len(token) > 255:
            raise ValueError(
                "A stored Meta token cannot fit the previous VARCHAR(255) column"
            )
        bind.execute(
            sa.text(
                "UPDATE store_meta_tokens SET access_token = :token WHERE id = :id"
            ),
            {"token": token, "id": row.id},
        )
    op.drop_index(
        "uq_channel_accounts_facebook_external",
        table_name="channel_accounts",
    )
    op.alter_column(
        "store_meta_tokens",
        "access_token",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
