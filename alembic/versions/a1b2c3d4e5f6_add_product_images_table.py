"""add_product_images_table

Revision ID: a1b2c3d4e5f6
Revises: new_store_meta_tokens_table
Create Date: 2026-11-03 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'new_store_meta_tokens_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create product_images table
    op.create_table(
        'product_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('image_url', sa.String(length=1024), nullable=False),
        sa.Column('thumbnail_url', sa.String(length=1024), nullable=True),
        sa.Column('mime_type', sa.String(length=50), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, default=False),
        sa.Column('display_order', sa.Integer(), nullable=False, default=0),
        sa.Column('processing_status', sa.String(length=20), nullable=False, default='PENDING'),
        sa.Column('embedding_model', sa.String(length=100), nullable=True),
        sa.Column('embedding_version', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for performance
    op.create_index('ix_product_images_store_id', 'product_images', ['store_id'])
    op.create_index('ix_product_images_product_id', 'product_images', ['product_id'])
    op.create_index('ix_product_images_store_product', 'product_images', ['store_id', 'product_id'])
    op.create_index('ix_product_images_processing_status', 'product_images', ['processing_status'])
    op.create_index('ix_product_images_is_primary', 'product_images', ['is_primary'])


def downgrade() -> None:
    op.drop_index('ix_product_images_is_primary', table_name='product_images')
    op.drop_index('ix_product_images_processing_status', table_name='product_images')
    op.drop_index('ix_product_images_store_product', table_name='product_images')
    op.drop_index('ix_product_images_product_id', table_name='product_images')
    op.drop_index('ix_product_images_store_id', table_name='product_images')
    op.drop_table('product_images')