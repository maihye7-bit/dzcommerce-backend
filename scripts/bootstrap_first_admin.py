"""
Bootstrap script: create the very first Super Admin and link him to a basic store.

Running this script on a fresh (empty) PostgreSQL database will:
  1. Verify no Super Admin exists yet.
  2. Prompt for an email and a password (read from stdin, never printed).
  3. Create a User with is_super_admin=True, is_active=True.
  4. Hash the password with the project's current hasher (bcrypt_sha256).
  5. Create a default Store ("Default Store") if one does not exist.
  6. Create a StoreUser entry granting the user OWNER role on that store.
  6. Commit everything in a single transaction; roll back on any error.

The script is **idempotent**: if a User with is_super_admin=True already exists,
it exits immediately without creating any new rows.

It does NOT:
- expose the password or its hash in logs or stdout,
- create ChannelAccount or StoreMetaToken,
- open any network port or external API,
- modify any other permission model.

Usage (local development / test database only):
    python scripts/bootstrap_first_admin.py

On Railway the same command can be run once against the production PostgreSQL
after the database has been initialized (migrations applied).  It must NOT be
run twice – the idempotency check prevents duplicate Super Admins.

"""

import sys
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_password
from app.database import Base, engine, SessionLocal, get_db
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole

# ---------------------------------------------------------------------------
# Helper: ask once for a string (no echo).  We use getpass so the terminal
# does not echo the password, but we fall back to input() if getpass is
# unavailable (e.g. non‑interactive CI).
# ---------------------------------------------------------------------------
def get_credentials() -> tuple[str, str]:
    import getpass

    email = input("Super Admin e-mail: ").strip()
    if not email:
        print("❌ Email cannot be empty.", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("Super Admin password: ")
    if not password:
        print("❌ Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    return email, password


# ---------------------------------------------------------------------------
def bootstrap() -> None:
    """
    Core bootstrap logic.  All DB work is done inside one SessionLocal()
    transaction – if anything fails we roll back completely.
    """
    # ------------------------------------------------------------------
    # 1️⃣  Verify no Super Admin exists yet
    # ------------------------------------------------------------------
    db: Session = SessionLocal()
    try:
        existing_super = db.query(User).filter(User.is_super_admin.is_(True)).first()
        if existing_super:
            print("✅ A Super Admin already exists (id=%s). Nothing to do." % existing_super.id)
            return
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Error while checking for existing Super Admin: %s" % exc, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2️⃣  Get e‑mail / password from the user
    # ------------------------------------------------------------------
    email, password = get_credentials()

    # ------------------------------------------------------------------
    # 3️⃣  Hash the password using the project's current hasher
    # ------------------------------------------------------------------
    try:
        hashed_pw = hash_password(password)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Failed to hash password: %s" % exc, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4️⃣  Create the User (is_super_admin=True, is_active=True)
    # ------------------------------------------------------------------
    try:
        new_user = User(
            email=email.lower(),
            hashed_password=hashed_pw,
            is_super_admin=True,
            is_active=True,
            full_name="Super Admin",
        )
        db.add(new_user)
        db.flush()  # assign an id without committing yet
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Failed to create User: %s" % exc, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 5️⃣  Create the default Store if it does not exist
    # ------------------------------------------------------------------
    try:
        store = db.query(Store).filter(Store.name == "Default Store").first()
        if not store:
            # Use a deterministic slug; if taken (very unlikely) add a suffix.
            base_slug = "default-store"
            existing = db.query(Store).filter(Store.slug == base_slug).first()
            slug = base_slug if not existing else "default-store-%d" % (db.query(Store).count() + 1)

            store = Store(
                name="Default Store",
                slug=slug,
                is_active=True,
                address="Main Branch",
                delivery_policy_text="Standard delivery policy",
                served_wilayas="All",
            )
            db.add(store)
            db.flush()  # assign store.id
        # else: store already exists – we reuse it
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Failed to create/find Store: %s" % exc, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 6️⃣  Link the user to the store as OWNER
    # ------------------------------------------------------------------
    try:
        membership = StoreUser(
            store_id=store.id,
            user_id=new_user.id,
            role=StoreRole.OWNER,
        )
        db.add(membership)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Failed to create StoreUser membership: %s" % exc, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 7️⃣  Single commit – if any step above failed we would have rolled back
    # ------------------------------------------------------------------
    try:
        db.commit()
        print("✅ Bootstrap completed successfully.")
        print("   • Super Admin: %s (id=%s)" % (new_user.email, new_user.id))
        print("   • Store: %s (id=%s)" % (store.name, store.id))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("❌ Commit failed, transaction rolled back: %s" % exc, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Ensure the database tables exist before we start working.
# This is a safety-net so the script can be run once on a fresh DB without
# requiring the user to manually run "alembic upgrade head" first.
# ---------------------------------------------------------------------------
from app.database import Base, engine  # noqa: F401 import for side effect (table creation)
Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    bootstrap()