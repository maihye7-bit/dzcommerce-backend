"""Corrective migration: add customer_memories table and preserve ai_usage_events.

Fixes revision 5e62604ab459 which accidentally dropped ai_usage_events
instead of creating customer_memories.

This migration:
1. Creates customer_memories table with correct schema (if not exists)
2. Validates existing schema if table already exists
3. Does NOT drop ai_usage_events (it was already recreated in migration 45948cf9d7b8)
4. Uses proper ownership tracking for safe downgrade
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic
revision = "fix_customer_memories_20261119"
down_revision = "db39a7d5b0a4"
branch_labels = None
depends_on = None

# Ownership tracking table - persisted metadata about what this migration created
_OWNERSHIP_TABLE = "migration_ownership_metadata"
_OWNERSHIP_MARKER = "customer_memories_created_by_fix_customer_memories"


def _table_exists(conn):
    """Check if customer_memories table exists using SQLAlchemy Inspector."""
    insp = inspect(conn)
    return "customer_memories" in insp.get_table_names()


def _get_fk_info(conn):
    """Get all foreign key information for customer_memories table."""
    insp = inspect(conn)
    return insp.get_foreign_keys("customer_memories")


def _get_indexes(conn):
    """Get all index information for customer_memories table."""
    insp = inspect(conn)
    return insp.get_indexes("customer_memories")


def _get_check_constraints(conn):
    """Get check constraints for customer_memories table."""
    insp = inspect(conn)
    return insp.get_check_constraints("customer_memories")


def _get_pk_constraint(conn):
    """Get primary key constraint for customer_memories table."""
    insp = inspect(conn)
    return insp.get_pk_constraint("customer_memories")


def _get_columns(conn):
    """Get all column information for customer_memories table."""
    insp = inspect(conn)
    return insp.get_columns("customer_memories")


def _validate_store_id_fk(fk_info):
    """Validate the store_id foreign key constraint has correct properties.

    Requirements:
    - references stores.id (referred_table='stores', referred_columns=['id'])
    - constrained_columns=['store_id']
    - ondelete='CASCADE'
    """
    for fk in fk_info:
        constrained_cols = fk.get("constrained_columns", [])
        if "store_id" in constrained_cols:
            if fk.get("referred_table") != "stores":
                return False, f"FK store_id refers to '{fk.get('referred_table')}', expected 'stores'"
            referred_cols = fk.get("referred_columns", [])
            if referred_cols != ["id"]:
                return False, f"FK store_id refers to columns {referred_cols}, expected ['id']"
            if fk.get("ondelete") != "CASCADE":
                return False, f"FK store_id has ondelete='{fk.get('ondelete')}', expected 'CASCADE'"
            return True, "store_id FK OK"
    return False, "store_id FK not found"


def _validate_customer_id_fk(fk_info):
    """Validate the customer_id foreign key constraint has correct properties.

    Requirements:
    - references customers.id (referred_table='customers', referred_columns=['id'])
    - constrained_columns=['customer_id']
    - ondelete='CASCADE'
    """
    for fk in fk_info:
        constrained_cols = fk.get("constrained_columns", [])
        if "customer_id" in constrained_cols:
            if fk.get("referred_table") != "customers":
                return False, f"FK customer_id refers to '{fk.get('referred_table')}', expected 'customers'"
            referred_cols = fk.get("referred_columns", [])
            if referred_cols != ["id"]:
                return False, f"FK customer_id refers to columns {referred_cols}, expected ['id']"
            if fk.get("ondelete") != "CASCADE":
                return False, f"FK customer_id has ondelete='{fk.get('ondelete')}', expected 'CASCADE'"
            return True, "customer_id FK OK"
    return False, "customer_id FK not found"


def _validate_schema(conn) -> None:
    """Validate that existing customer_memories table matches expected schema.

    Raises RuntimeError if schema is incompatible (but does not modify data).
    """
    errors = []

    # Get column info
    cols = {c["name"]: c for c in _get_columns(conn)}

    # Check required columns exist
    expected_columns = {
        "id": {"type": "UUID", "nullable": False},
        "store_id": {"type": "UUID", "nullable": False},
        "customer_id": {"type": "UUID", "nullable": False},
        "memory_type": {"type": "VARCHAR", "nullable": False, "length": 50},
        "key": {"type": "VARCHAR", "nullable": False, "length": 100},
        "value": {"type": "VARCHAR", "nullable": False, "length": 500},
        "confidence": {"type": "FLOAT", "nullable": False},
        "source": {"type": "VARCHAR", "nullable": True, "length": 100},
        "created_at": {"type": "TIMESTAMP", "nullable": False},
        "updated_at": {"type": "TIMESTAMP", "nullable": False},
    }

    for col, exp in expected_columns.items():
        got = cols.get(col)
        if not got:
            errors.append(f"missing column: {col}")
            continue

        # Check nullable
        if got.get("nullable") != exp["nullable"]:
            errors.append(
                f"column '{col}': nullable mismatch (expected {exp['nullable']}, got {got.get('nullable')})"
            )

        # Check type compatibility
        got_type = str(got.get("type", "")).upper()
        exp_type = exp["type"].upper()

        if exp_type == "UUID":
            if "UUID" not in got_type:
                errors.append(f"column '{col}': expected UUID type, got {got_type}")
        elif exp_type == "VARCHAR":
            if "VARCHAR" not in got_type and "CHARACTER" not in got_type:
                errors.append(f"column '{col}': expected VARCHAR type, got {got_type}")
        elif exp_type == "FLOAT":
            if "FLOAT" not in got_type and "DOUBLE" not in got_type and "REAL" not in got_type:
                errors.append(f"column '{col}': expected FLOAT type, got {got_type}")
        elif exp_type == "TIMESTAMP":
            if "DATE" not in got_type.upper() and "TIMESTAMP" not in got_type.upper():
                errors.append(f"column '{col}': expected TIMESTAMP type, got {got_type}")

        # Check length for VARCHAR columns
        if "length" in exp and exp["length"] is not None:
            col_len = getattr(got.get("type"), "length", None)
            if col_len != exp["length"]:
                errors.append(f"column '{col}': length mismatch (expected {exp['length']}, got {col_len})")

    # Check primary key
    pk = _get_pk_constraint(conn)
    if pk.get("constrained_columns") != ["id"]:
        errors.append(f"primary key mismatch: expected ['id'], got {pk.get('constrained_columns')}")

    # Validate store_id foreign key
    fk_info = _get_fk_info(conn)
    valid, msg = _validate_store_id_fk(fk_info)
    if not valid:
        errors.append(f"store_id FK validation failed: {msg}")

    # Validate customer_id foreign key
    valid, msg = _validate_customer_id_fk(fk_info)
    if not valid:
        errors.append(f"customer_id FK validation failed: {msg}")

    # Check constraint
    checks = _get_check_constraints(conn)
    ck_names = [c.get("name") for c in checks]
    if "ck_memory_confidence_range" not in ck_names:
        errors.append("missing check constraint: ck_memory_confidence_range")

    # Raise if any errors
    if errors:
        raise RuntimeError(
            "customer_memories schema validation failed:\n  "
            + "\n  ".join(errors)
        )


def _ensure_ownership_table(conn):
    """Create the ownership metadata table if it doesn't exist.

    This table persists information about what this migration created,
    surviving separate upgrade and downgrade executions.
    """
    inspector = inspect(conn)
    if _OWNERSHIP_TABLE not in inspector.get_table_names():
        conn.execute(sa.text(f"""
            CREATE TABLE {_OWNERSHIP_TABLE} (
                marker TEXT PRIMARY KEY,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))


def _migration_created_table(conn) -> bool:
    """Check if this migration created the customer_memories table using persistent metadata.

    Uses a dedicated ownership tracking table that records whether this
    migration created the customer_memories table. This survives separate
    upgrade and downgrade executions.
    """
    # First ensure ownership table exists
    _ensure_ownership_table(conn)

    # Check if we recorded that we created this table
    result = conn.execute(sa.text(f"""
        SELECT 1 FROM {_OWNERSHIP_TABLE} WHERE marker = :marker
    """), {"marker": _OWNERSHIP_MARKER})

    return result.scalar() is not None


def _record_ownership(conn, created: bool):
    """Record ownership state in the metadata table."""
    if created:
        # Record that we created customer_memories
        conn.execute(sa.text(f"""
            INSERT INTO {_OWNERSHIP_TABLE} (marker) VALUES (:marker)
            ON CONFLICT (marker) DO NOTHING
        """), {"marker": _OWNERSHIP_MARKER})
    else:
        # Record that customer_memories was pre-existing
        conn.execute(sa.text(f"""
            INSERT INTO {_OWNERSHIP_TABLE} (marker) VALUES (:marker)
            ON CONFLICT (marker) DO NOTHING
        """), {"marker": f"{_OWNERSHIP_MARKER}_preexisting"})


def upgrade() -> None:
    """Create customer_memories table if it doesn't exist.

    If the table already exists, validate its schema matches expectations.
    This migration does NOT touch ai_usage_events table.
    """
    # Alembic owns this Connection and its transaction; never reopen or close it.
    conn = op.get_bind()

    if _table_exists(conn):
        # Table exists - validate schema
        _validate_schema(conn)
        # Record that table was pre-existing
        _record_ownership(conn, created=False)
        return

    # Create table and indexes using op methods for Alembic compatibility
    op.create_table(
        "customer_memories",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("memory_type", sa.String(50), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="1.0"
        ),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence_range"),
    )

    op.create_index(
        op.f("ix_customer_memories_store_customer"),
        "customer_memories",
        ["store_id", "customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_memories_type"),
        "customer_memories",
        ["store_id", "memory_type"],
        unique=False,
    )

    # Ensure ownership table exists and record that we created customer_memories
    _ensure_ownership_table(conn)
    conn.execute(sa.text(f"""
        INSERT INTO {_OWNERSHIP_TABLE} (marker) VALUES (:marker)
        ON CONFLICT (marker) DO NOTHING
    """), {"marker": _OWNERSHIP_MARKER})


    # This migration does NOT drop or recreate ai_usage_events
    # that table was handled by earlier migrations and should be preserved


def downgrade() -> None:
    """Remove customer_memories table only if this migration created it.

    Safety guarantees:
    1. Never removes a pre-existing table
    2. Never touches ai_usage_events
    3. Safe to run multiple times (idempotent)
    4. Uses persistent metadata to determine ownership
    """
    # Alembic owns this Connection and its transaction; never reopen or close it.
    conn = op.get_bind()

    if not _table_exists(conn):
        return

    # Check if this migration owns this table using persistent metadata
    if _migration_created_table(conn):
        # We created it - remove it
        op.drop_index(
            op.f("ix_customer_memories_store_customer"),
            table_name="customer_memories"
        )
        op.drop_index(
            op.f("ix_customer_memories_type"),
            table_name="customer_memories"
        )
        op.drop_table("customer_memories")

        # Record that we removed it
        conn.execute(sa.text(f"""
            DELETE FROM {_OWNERSHIP_TABLE} WHERE marker = :marker
        """), {"marker": _OWNERSHIP_MARKER})
    # If not owned by this migration, we leave the table intact


    # This migration does NOT touch ai_usage_events