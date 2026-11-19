"""Merge migration to resolve heads divergence.

This merge resolves the divergence between:
- 6f3a1c9d2b84 (main branch - creates support tables)
- fix_customer_memories_20261119 (fix branch - creates customer_memories)

This migration ensures a linear history going forward.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "merge_cust_mem_heads"
down_revision = ("6f3a1c9d2b84", "fix_customer_memories_20261119")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op upgrade - this is just a merge migration.

    Both 6f3a1c9d2b84 and fix_customer_memories_20261119 have already run
    their respective schema changes:
    - 6f3a1c9d2b84 creates: human_handoffs, sales_opportunities
    - fix_customer_memories_20261119 creates: customer_memories

    This merge simply marks the point where both branches are combined.
    """
    pass


def downgrade() -> None:
    """No-op downgrade - this is just a merge migration.

    Downgrade cannot safely revert the merge without knowing which branch
    changes should be reverted. Users should downgrade individually if needed:
    - For customer_memories: apply fix_customer_memories_20261119 downgrade
    - For support tables: apply 6f3a1c9d2b84 (but see note about pre-existing data)
    """
    pass