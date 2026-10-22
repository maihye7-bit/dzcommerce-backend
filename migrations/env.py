from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# --- Path Configuration for Imports ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# --- Path Configuration for Imports ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Project Imports ---
from app.database import Base, engine

# IMPORTANT: Import ALL models here so Alembic sees them in metadata
# We added the new commerce models: product, inventory, customer, order
from app.models import user, store, conversation
from app.models import product, inventory, customer, order

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    if not url:
        raise RuntimeError("Could not find DATABASE_URL in environment or alembic.ini")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine

    with connectable.connect() as connection:
        # --- AUTO-CLEANUP: Prevents "Can't locate revision" errors ---
        try:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version;"))
            connection.commit()
            print("🧹 Cleaned up old alembic_version table.")
        except Exception:
            pass
        # -------------------------------------------------------------

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
