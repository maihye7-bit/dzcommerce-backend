import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "6f3a1c9d2b84_create_support_tables.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "create_support_tables_migration",
        MIGRATION_PATH,
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run_migration(connection, operation):
    with Operations.context(MigrationContext.configure(connection)):
        operation()


def _create_referenced_tables(connection):
    for table in ("stores", "customers", "conversations", "orders", "products"):
        connection.execute(
            text(f"CREATE TABLE {table} (id CHAR(32) PRIMARY KEY)")
        )


def test_support_tables_migration_creates_expected_schema_idempotently():
    migration = _load_migration()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_referenced_tables(connection)
        _run_migration(connection, migration.upgrade)
        _run_migration(connection, migration.upgrade)

        inspector = inspect(connection)
        assert inspector.has_table("human_handoffs")
        assert inspector.has_table("sales_opportunities")
        assert {
            index["name"] for index in inspector.get_indexes("human_handoffs")
        } == {
            "ix_human_handoffs_store_id",
            "ix_human_handoffs_conversation_id",
        }
        assert {
            index["name"] for index in inspector.get_indexes("sales_opportunities")
        } == {
            "ix_sales_opp_store_customer",
            "ix_sales_opp_status",
        }
        handoff_fks = {
            fk["constrained_columns"][0]: fk["options"].get("ondelete")
            for fk in inspector.get_foreign_keys("human_handoffs")
        }
        opportunity_fks = {
            fk["constrained_columns"][0]: fk["options"].get("ondelete")
            for fk in inspector.get_foreign_keys("sales_opportunities")
        }
        assert handoff_fks == {
            "store_id": "CASCADE",
            "conversation_id": "CASCADE",
            "customer_id": "CASCADE",
        }
        assert opportunity_fks == {
            "store_id": "CASCADE",
            "customer_id": "CASCADE",
            "related_order_id": "SET NULL",
            "related_product_id": "SET NULL",
        }

        _run_migration(connection, migration.downgrade)
        assert inspect(connection).has_table("human_handoffs")
        assert inspect(connection).has_table("sales_opportunities")
    engine.dispose()


def test_support_tables_migration_does_not_drop_preexisting_tables_or_rows():
    migration = _load_migration()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_referenced_tables(connection)
        connection.execute(
            text("CREATE TABLE human_handoffs (id INTEGER PRIMARY KEY, summary TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE sales_opportunities "
                "(id INTEGER PRIMARY KEY, notes TEXT)"
            )
        )
        connection.execute(
            text("INSERT INTO human_handoffs (id, summary) VALUES (1, 'keep')")
        )
        connection.execute(
            text("INSERT INTO sales_opportunities (id, notes) VALUES (2, 'keep')")
        )

        _run_migration(connection, migration.upgrade)
        _run_migration(connection, migration.downgrade)

        assert connection.execute(
            text("SELECT summary FROM human_handoffs WHERE id = 1")
        ).scalar_one() == "keep"
        assert connection.execute(
            text("SELECT notes FROM sales_opportunities WHERE id = 2")
        ).scalar_one() == "keep"
    engine.dispose()
