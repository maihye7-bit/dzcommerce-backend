import os
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_alembic():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable not found.")
        return

    # Convert sqlalchemy URL to psycopg2 if needed
    if database_url.startswith("postgresql+psycopg2://"):
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql://")

    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()

        # Check if alembic_version exists
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version');")
        exists = cur.fetchone()[0]

        if exists:
            cur.execute("SELECT version_num FROM alembic_version;")
            current_version = cur.fetchone()
            logger.info(f"Current Alembic version in DB: {current_version}")

            # The correct head version based on current code
            correct_head = "9f82d11ab3c4"

            logger.info(f"Correcting version to: {correct_head}")
            cur.execute("UPDATE alembic_version SET version_num = %s;", (correct_head,))
            conn.commit()
            logger.info("✅ Alembic version updated successfully.")
        else:
            logger.warning("alembic_version table does not exist. No fix needed (alembic upgrade will create it).")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error fixing Alembic: {e}")

if __name__ == "__main__":
    fix_alembic()
