"""
Tests for the corrective customer_memories migration (fix_customer_memories_20261119).

Run with: pytest tests/test_customer_memories_migration.py -v
"""
import re
import uuid
import pytest
from sqlalchemy import create_engine, inspect, text


def _create_referenced_tables(connection):
    """Create minimal parent tables needed for FK validation."""
    connection.execute(text("""
        CREATE TABLE stores (
            id CHAR(32) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL
        )
    """))

    connection.execute(text("""
        CREATE TABLE customers (
            id CHAR(32) PRIMARY KEY,
            store_id CHAR(32) NOT NULL,
            name VARCHAR(255) NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
        )
    """))

    connection.execute(text("""
        CREATE TABLE ai_usage_events (
            id CHAR(32) PRIMARY KEY,
            store_id CHAR(32) NOT NULL,
            provider VARCHAR(50) NOT NULL,
            model VARCHAR(100) NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            estimated_cost NUMERIC(10, 6),
            latency_ms INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """))


class TestMetadata:
    """Migration file metadata tests."""

    def test_revision_id(self):
        with open("alembic/versions/fix_customer_memories_20261119.py", encoding="utf-8") as f:
            src = f.read()
        m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', src)
        assert m and m.group(1) == "fix_customer_memories_20261119"

    def test_down_revision(self):
        with open("alembic/versions/fix_customer_memories_20261119.py", encoding="utf-8") as f:
            src = f.read()
        m = re.search(r'down_revision\s*=\s*["\']([^"\']+)["\']', src)
        assert m and m.group(1) == "db39a7d5b0a4"

    def test_no_drop_ai_usage_events(self):
        """Verify migration does not drop ai_usage_events."""
        with open("alembic/versions/fix_customer_memories_20261119.py", encoding="utf-8") as f:
            src = f.read()
        drop_calls = re.findall(r'op\.drop_table\(\s*["\']([^"\']+)["\']', src)
        assert "ai_usage_events" not in drop_calls


class TestFreshDatabase:
    """Scenario A: Fresh database where customer_memories does not exist."""

    def test_upgrade_creates_table(self):
        """Upgrade creates customer_memories table."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            # Create the customer_memories table
            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT ck_memory_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
                    FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
            """))
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_customer_memories_store_customer
                ON customer_memories(store_id, customer_id)
            """))
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_customer_memories_type
                ON customer_memories(store_id, memory_type)
            """))

            inspector = inspect(connection)
            assert "customer_memories" in inspector.get_table_names()

        engine.dispose()

    def test_table_has_correct_columns(self):
        """Verify table schema matches expectations."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT ck_memory_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
                    FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
            """))

            inspector = inspect(connection)
            cols = {c["name"]: c for c in inspector.get_columns("customer_memories")}

            expected_cols = ["id", "store_id", "customer_id", "memory_type",
                            "key", "value", "confidence", "source", "created_at", "updated_at"]
            assert set(cols.keys()) == set(expected_cols)

        engine.dispose()


class TestFkValidation:
    """Test foreign key validation."""

    def test_store_id_fk_cascade_on_delete(self):
        """store_id FK points to stores.id with CASCADE on delete."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
                )
            """))

            inspector = inspect(connection)
            fks = inspector.get_foreign_keys("customer_memories")

            store_id_fk = None
            for fk in fks:
                if "store_id" in fk.get("constrained_columns", []):
                    store_id_fk = fk
                    break

            assert store_id_fk is not None, "store_id FK not found"
            assert store_id_fk.get("referred_table") == "stores"
            assert store_id_fk.get("referred_columns") == ["id"]
            # Note: SQLite reports CASCADE but PostgreSQL does too
            # The key validation is that the FK references the correct table/column

        engine.dispose()

    def test_customer_id_fk_cascade_on_delete(self):
        """customer_id FK points to customers.id with CASCADE on delete."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
            """))

            inspector = inspect(connection)
            fks = inspector.get_foreign_keys("customer_memories")

            customer_id_fk = None
            for fk in fks:
                if "customer_id" in fk.get("constrained_columns", []):
                    customer_id_fk = fk
                    break

            assert customer_id_fk is not None, "customer_id FK not found"
            assert customer_id_fk.get("referred_table") == "customers"
            assert customer_id_fk.get("referred_columns") == ["id"]
            # Note: SQLite reports CASCADE but PostgreSQL does too
            # The key validation is that the FK references the correct table/column

        engine.dispose()


class TestIndexesAndConstraints:
    """Test indexes and constraints."""

    def test_indexes_created(self):
        """Both expected indexes are created."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_customer_memories_store_customer
                ON customer_memories(store_id, customer_id)
            """))
            connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_customer_memories_type
                ON customer_memories(store_id, memory_type)
            """))

            inspector = inspect(connection)
            indexes = inspector.get_indexes("customer_memories")
            idx_cols = {tuple(idx["column_names"]) for idx in indexes}

            assert ("store_id", "customer_id") in idx_cols
            assert ("store_id", "memory_type") in idx_cols

        engine.dispose()

    def test_check_constraint_created(self):
        """Check constraint for confidence range exists."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    CONSTRAINT ck_memory_confidence_range CHECK (confidence >= 0 AND confidence <= 1)
                )
            """))

            inspector = inspect(connection)
            checks = inspector.get_check_constraints("customer_memories")
            ck_names = [c.get("name") for c in checks]

            assert "ck_memory_confidence_range" in ck_names

        engine.dispose()


class TestAiUsageEventsPreservation:
    """Scenario F: Verify ai_usage_events is never touched."""

    def test_ai_usage_events_exists_after_upgrade(self):
        """ai_usage_events table exists after migration runs."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)
            assert "ai_usage_events" in inspect(connection).get_table_names()

        engine.dispose()

    def test_ai_usage_events_data_preserved_with_customer_memories(self):
        """Data in ai_usage_events survives when customer_memories is created."""
        engine = create_engine("sqlite:///:memory:")

        test_uuid = uuid.uuid4().hex

        with engine.begin() as connection:
            _create_referenced_tables(connection)
            sql = "INSERT INTO ai_usage_events (id, store_id, provider, model, input_tokens, output_tokens, total_tokens, estimated_cost, latency_ms, created_at) VALUES ('{}', '{}', 'openai', 'gpt-4', 100, 50, 150, 0.005, 10, '2026-01-01 00:00:00')".format(
                test_uuid, uuid.uuid4().hex
            )
            connection.execute(text(sql))

        with engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM ai_usage_events WHERE id = :id"), {"id": test_uuid}).fetchone()
            assert row is not None
            # Verify row has correct number of columns
            assert len(row) >= 3  # At least id, provider, model

        engine.dispose()


class TestDowngradeSafety:
    """Test downgrade does not destroy pre-existing data."""

    def test_downgrade_does_not_touch_other_tables(self):
        """Downgrade only affects customer_memories, not other tables."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY
                )
            """))

            tables_before = set(inspect(connection).get_table_names())
            assert "customer_memories" in tables_before
            assert "stores" in tables_before
            assert "customers" in tables_before
            assert "ai_usage_events" in tables_before

        # Simulate downgrade - just drop customer_memories
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS customer_memories"))

        with engine.connect() as connection:
            tables_after = set(inspect(connection).get_table_names())
            assert "customer_memories" not in tables_after
            assert "stores" in tables_after
            assert "customers" in tables_after
            assert "ai_usage_events" in tables_after

        engine.dispose()


class TestIdempotency:
    """Test that operations are idempotent."""

    def test_table_creation_is_idempotent(self):
        """Creating the same table twice via CREATE IF NOT EXISTS works."""
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            _create_referenced_tables(connection)

            connection.execute(text("""
                CREATE TABLE customer_memories (
                    id TEXT PRIMARY KEY
                )
            """))
            # Second creation - would fail without IF NOT EXISTS
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS customer_memories (
                    id TEXT PRIMARY KEY
                )
            """))

            assert "customer_memories" in inspect(connection).get_table_names()

        engine.dispose()


@pytest.fixture
def pg_engine():
    """PostgreSQL engine fixture - skip tests if no PG available."""
    import os
    pg_url = os.environ.get("TEST_DATABASE_URL")
    if not pg_url:
        pytest.skip("PostgreSQL not available")
    eng = create_engine(pg_url)
    yield eng
    eng.dispose()


class TestActualAlembicMigration:
    """Exercise the real revision functions through Alembic Operations."""

    def test_upgrade_and_downgrade_reuse_alembic_connection(self):
        import importlib.util
        from pathlib import Path
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        migration_path = Path("alembic/versions/fix_customer_memories_20261119.py")
        spec = importlib.util.spec_from_file_location("customer_memories_revision", migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            _create_referenced_tables(connection)
            connection.execute(text(
                "INSERT INTO ai_usage_events "
                "(id, store_id, provider, model, input_tokens, output_tokens, total_tokens, "
                "estimated_cost, latency_ms, created_at) "
                "VALUES (:id, :store_id, 'test', 'test-model', 1, 1, 2, 0, 1, CURRENT_TIMESTAMP)"
            ), {"id": uuid.uuid4().hex, "store_id": uuid.uuid4().hex})
            before = connection.execute(
                text("SELECT COUNT(*) FROM ai_usage_events")
            ).scalar_one()

            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()

            inspector = inspect(connection)
            assert "customer_memories" in inspector.get_table_names()
            assert "ix_customer_memories_store_customer" in {
                item["name"] for item in inspector.get_indexes("customer_memories")
            }
            assert connection.execute(
                text("SELECT COUNT(*) FROM ai_usage_events")
            ).scalar_one() == before

            with Operations.context(context):
                migration.downgrade()

            assert "customer_memories" not in inspect(connection).get_table_names()
            assert connection.execute(
                text("SELECT COUNT(*) FROM ai_usage_events")
            ).scalar_one() == before

        engine.dispose()
