"""merge migration heads

Revision ID: db39a7d5b0a4
Revises: 31c7a5d09b42, 8d9c7dcb4f3d
Create Date: 2026-10-19 10:25:54.389384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db39a7d5b0a4'
down_revision: Union[str, None] = ('31c7a5d09b42', '8d9c7dcb4f3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
