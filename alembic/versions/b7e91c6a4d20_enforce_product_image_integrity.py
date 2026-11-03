"""enforce product image tenant and primary integrity

Revision ID: b7e91c6a4d20
Revises: a1b2c3d4e5f6
Create Date: 2026-11-03 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "b7e91c6a4d20"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_products_store_id_id",
        "products",
        ["store_id", "id"],
    )
    op.drop_constraint(
        "product_images_product_id_fkey",
        "product_images",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_product_images_store_product",
        "product_images",
        "products",
        ["store_id", "product_id"],
        ["store_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_product_images_storage_key",
        "product_images",
        ["storage_key"],
    )
    op.create_index(
        "uq_product_images_primary_per_product",
        "product_images",
        ["store_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        sqlite_where=sa.text("is_primary = 1"),
    )
    op.create_index(
        "ix_product_images_product_order",
        "product_images",
        ["store_id", "product_id", "display_order", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_images_product_order",
        table_name="product_images",
    )
    op.drop_index(
        "uq_product_images_primary_per_product",
        table_name="product_images",
    )
    op.drop_constraint(
        "uq_product_images_storage_key",
        "product_images",
        type_="unique",
    )
    op.drop_constraint(
        "fk_product_images_store_product",
        "product_images",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "product_images_product_id_fkey",
        "product_images",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_products_store_id_id",
        "products",
        type_="unique",
    )
