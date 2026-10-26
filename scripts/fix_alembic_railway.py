import os
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_alembic():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL environment variable not found in fix_alembic_railway.py!")
        return

    logger.info(f"Raw DATABASE_URL found (length: {len(database_url)})")

    # Normalize URL for psycopg2
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    elif "+" in database_url:
        # e.g. postgresql+psycopg2:// -> postgresql://
        scheme, rest = database_url.split("://", 1)
        base_scheme = scheme.split("+")[0]
        database_url = f"{base_scheme}://{rest}"

    try:
        logger.info("Attempting connection to database for Alembic fix...")
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()

        # Check if alembic_version exists
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version');")
        exists = cur.fetchone()[0]

        if exists:
            cur.execute("SELECT version_num FROM alembic_version;")
            current_version = cur.fetchone()
            logger.info(f"Current Alembic version in DB: {current_version}")

            # Correct head version
            correct_head = "9f82d11ab3c4"

            logger.info(f"Forcing Alembic version update from {current_version} to: {correct_head}")
            cur.execute("UPDATE alembic_version SET version_num = %s;", (correct_head,))
            conn.commit()
            logger.info("✅ Alembic version successfully updated in DB!")
        else:
            logger.warning("⚠️ alembic_version table does not exist yet. Creating it and stamping head.")
            cur.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);")
            cur.execute("INSERT INTO alembic_version (version_num) VALUES (%s);", ("9f82d11ab3c4",))
            conn.commit()
            logger.info("✅ alembic_version table created and stamped with head!")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ CRITICAL Error fixing Alembic in script: {e}", exc_info=True)

if __name__ == "__main__":
    fix_alembic()
