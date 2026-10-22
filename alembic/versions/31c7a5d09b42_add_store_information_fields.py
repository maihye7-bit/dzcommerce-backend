"""Add verified store information fields.

Revision ID: 31c7a5d09b42
Revises: 45948cf9d7b8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "31c7a5d09b42"
down_revision: Union[str, None] = "45948cf9d7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("address", sa.Text(), nullable=True))
    op.add_column(
        "stores", sa.Column("delivery_policy_text", sa.Text(), nullable=True)
    )
    op.add_column("stores", sa.Column("served_wilayas", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "served_wilayas")
    op.drop_column("stores", "delivery_policy_text")
    op.drop_column("stores", "address")
