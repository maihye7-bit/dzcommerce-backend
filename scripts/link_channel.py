"""Create, list, and remove store-to-platform account mappings."""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import IntegrityError, SQLAlchemyError  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.channel_account import ChannelAccount  # noqa: E402
from app.models.store import Store  # noqa: E402

VALID_CHANNELS = ("facebook", "instagram", "whatsapp")


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid UUID: {value}"
        ) from exc


def parse_channel(value: str) -> str:
    if value not in VALID_CHANNELS:
        raise argparse.ArgumentTypeError(
            "Invalid channel. Use: facebook, instagram, whatsapp"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage channel account mappings for stores."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--list",
        action="store_true",
        help="List all channel account mappings.",
    )
    action.add_argument(
        "--remove",
        type=parse_uuid,
        metavar="UUID",
        help="Remove a mapping by its UUID.",
    )
    parser.add_argument("--store", type=parse_uuid, help="Target store UUID.")
    parser.add_argument(
        "--channel",
        type=parse_channel,
        help="Channel: facebook, instagram, or whatsapp.",
    )
    parser.add_argument("--account-id", help="External platform account ID.")
    parser.add_argument("--account-name", help="Optional display name.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        if any((args.store, args.channel, args.account_id, args.account_name)):
            parser.error("--list cannot be combined with mapping arguments.")
        return list_mappings()
    if args.remove is not None:
        if any((args.store, args.channel, args.account_id, args.account_name)):
            parser.error("--remove cannot be combined with mapping arguments.")
        return remove_mapping(args.remove)
    if args.store is None or args.channel is None or not args.account_id:
        parser.error(
            "--store, --channel, and --account-id are required to create a mapping."
        )
    return create_mapping(
        args.store,
        args.channel,
        args.account_id,
        args.account_name,
    )


def list_mappings() -> int:
    try:
        with SessionLocal() as db:
            mappings = (
                db.query(ChannelAccount)
                .order_by(ChannelAccount.created_at.asc(), ChannelAccount.id.asc())
                .all()
            )
            if not mappings:
                print("No channel mappings found.")
                return 0
            for mapping in mappings:
                print(
                    f"{mapping.id} store={mapping.store_id} "
                    f"channel={mapping.channel} "
                    f"account_id={mapping.external_account_id} "
                    f"account_name={mapping.external_account_name or '-'} "
                    f"active={mapping.is_active}"
                )
        return 0
    except SQLAlchemyError as exc:
        print(f"Failed to list channel mappings: {exc}", file=sys.stderr)
        return 1


def create_mapping(
    store_id: uuid.UUID,
    channel: str,
    account_id: str,
    account_name: str | None,
) -> int:
    if not account_id.strip():
        print("Account ID must not be empty.", file=sys.stderr)
        return 2

    try:
        with SessionLocal() as db:
            store = (
                db.query(Store)
                .filter(Store.id == store_id, Store.is_active.is_(True))
                .one_or_none()
            )
            if store is None:
                print("Store was not found or is inactive.", file=sys.stderr)
                return 1

            existing = (
                db.query(ChannelAccount.id)
                .filter(
                    ChannelAccount.store_id == store_id,
                    ChannelAccount.channel == channel,
                )
                .one_or_none()
            )
            if existing is not None:
                print(
                    f"A {channel} mapping already exists for this store.",
                    file=sys.stderr,
                )
                return 1

            mapping = ChannelAccount(
                store_id=store_id,
                channel=channel,
                external_account_id=account_id,
                external_account_name=account_name,
                is_active=True,
            )
            db.add(mapping)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                print(
                    f"A {channel} mapping already exists for this store.",
                    file=sys.stderr,
                )
                return 1
            print(f"Mapping created: {mapping.id} channel={channel}")
            return 0
    except SQLAlchemyError as exc:
        print(f"Failed to create channel mapping: {exc}", file=sys.stderr)
        return 1


def remove_mapping(mapping_id: uuid.UUID) -> int:
    try:
        with SessionLocal() as db:
            mapping = (
                db.query(ChannelAccount)
                .filter(ChannelAccount.id == mapping_id)
                .one_or_none()
            )
            if mapping is None:
                print("Channel mapping was not found.", file=sys.stderr)
                return 1
            db.delete(mapping)
            db.commit()
            print(f"Mapping removed: {mapping_id}")
            return 0
    except SQLAlchemyError as exc:
        print(f"Failed to remove channel mapping: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
