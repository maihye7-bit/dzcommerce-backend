"""Mark an existing user as a super admin for the global dashboard."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.user import User


def make_super_admin(db: Session, *, username: str) -> User:
    normalized = username.strip().casefold()
    if not normalized:
        raise ValueError("Username cannot be empty.")

    user = db.query(User).filter(User.email == normalized).one_or_none()
    if user is None:
        raise ValueError(f"No user found for username '{username}'.")

    user.is_super_admin = True
    user.is_superuser = True
    db.commit()
    db.refresh(user)
    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant super-admin access to an existing dashboard user."
    )
    parser.add_argument("--username", required=True, help="Existing user/email")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        user = make_super_admin(db, username=args.username)
    except ValueError as exc:
        db.rollback()
        print(f"Super-admin update failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"User '{user.email}' is now a super admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
