"""Create an owner account for an existing store."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.security import hash_password
from app.database import SessionLocal
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User


class BootstrapError(Exception):
    """Expected account bootstrap failure safe to show on a terminal."""


def create_owner(
    db: Session,
    *,
    store_slug: str,
    username: str,
    password: str,
) -> User:
    normalized_username = username.strip().casefold()
    if not normalized_username:
        raise BootstrapError("Username cannot be empty.")
    if not password:
        raise BootstrapError("Password cannot be empty.")

    store = db.query(Store).filter(Store.slug == store_slug).one_or_none()
    if store is None:
        raise BootstrapError("No store exists with the supplied slug.")

    existing_user = (
        db.query(User)
        .filter(User.email == normalized_username)
        .one_or_none()
    )
    if existing_user is not None:
        existing_membership = (
            db.query(StoreUser)
            .filter(
                StoreUser.user_id == existing_user.id,
                StoreUser.store_id == store.id,
                StoreUser.role == StoreRole.OWNER,
            )
            .one_or_none()
        )
        if existing_membership is not None:
            raise BootstrapError(
                "An owner with this username is already linked to this store."
            )
        raise BootstrapError("This username is already in use.")

    user = User(
        email=normalized_username,
        hashed_password=hash_password(password),
        full_name=normalized_username,
        is_active=True,
        is_superuser=False,
        is_super_admin=False,
    )
    db.add(user)
    db.flush()
    db.add(
        StoreUser(
            store_id=store.id,
            user_id=user.id,
            role=StoreRole.OWNER,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BootstrapError("The username or store membership already exists.")
    db.refresh(user)
    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an owner account linked to an existing store."
    )
    parser.add_argument("--store-slug", required=True, help="Existing store slug")
    parser.add_argument("--username", required=True, help="Unique login username")
    parser.add_argument("--password", required=True, help="Owner password")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        create_owner(
            db,
            store_slug=args.store_slug,
            username=args.username,
            password=args.password,
        )
    except BootstrapError as exc:
        db.rollback()
        print(f"Owner creation failed: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        db.rollback()
        print("Owner creation failed because of a database error.", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"Owner '{args.username.strip()}' created for store "
        f"'{args.store_slug}'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
