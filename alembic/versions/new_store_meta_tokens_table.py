"""Create store_meta_tokens table

Revision ID: new_store_meta_tokens_table
Revises: 9f82d11ab3c4
Create Date: 2026-10-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = 'new_store_meta_tokens_table'
down_revision = '9f82d11ab3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'store_meta_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('page_id', sa.String(length=255), nullable=False),
        sa.Column('page_name', sa.String(length=255), nullable=False),
        sa.Column('access_token', sa.String(length=255), nullable=False),
        sa.Column('instagram_page_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', name='uq_store_meta_token_store_id'),
    )
    op.create_index('ix_store_meta_tokens_store_id', 'store_meta_tokens', ['store_id'])


def downgrade() -> None:
    op.drop_table('store_meta_tokens')
