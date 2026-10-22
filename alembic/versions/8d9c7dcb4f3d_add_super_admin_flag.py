"""Add is_super_admin flag to users

Revision ID: 8d9c7dcb4f3d
Revises: e9f12e382b2c
Create Date: 2026-10-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d9c7dcb4f3d"
down_revision: Union[str, None] = "e9f12e382b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_super_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "is_super_admin", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_super_admin")
