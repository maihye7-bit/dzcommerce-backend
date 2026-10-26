"""
Seed Script for DzCommerce.

Ensures at least one default store ("Default Store") exists in the database
so that incoming webhooks or dev setups can run without cold-start failure.
"""

import logging
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.store import Store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed_default_store(db: Session) -> Store:
    """Checks if a 'Default Store' exists, creating it if necessary."""
    store = db.query(Store).filter(Store.name == "Default Store").first()
    if not store:
        # Check if slug 'default-store' is taken
        existing_slug = db.query(Store).filter(Store.slug == "default-store").first()
        slug = "default-store" if not existing_slug else f"default-store-{db.query(Store).count() + 1}"

        store = Store(
            name="Default Store",
            slug=slug,
            is_active=True,
            address="Main Branch",
            delivery_policy_text="Standard delivery policy",
            served_wilayas="All",
        )
        db.add(store)
        db.commit()
        db.refresh(store)
        logger.info("Created 'Default Store' with ID: %s", store.id)
    else:
        logger.info("'Default Store' already exists with ID: %s", store.id)
    return store


def main():
    db = SessionLocal()
    try:
        seed_default_store(db)
    except Exception as e:
        db.rollback()
        logger.error("Error during seeding: %s", str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
