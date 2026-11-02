"""Dry-run-first reset for one Messenger test conversation."""

import argparse
import json
import sys

from app.database import SessionLocal
from app.services.messenger_test_conversation_reset import (
    preview_messenger_test_conversation_reset,
    reset_messenger_test_conversation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or reset one Facebook Messenger test conversation. "
            "A store ID is always required to enforce tenant ownership."
        )
    )
    parser.add_argument("--store-id", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--conversation-id")
    selector.add_argument("--psid")
    selector.add_argument("--test-customer-id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the reset; without this flag the command is read-only.",
    )
    parser.add_argument(
        "--confirm-conversation-id",
        help="Must exactly match the resolved conversation ID when using --execute.",
    )
    parser.add_argument(
        "--delete-unconfirmed-test-order-id",
        action="append",
        default=[],
        help=(
            "Explicitly select one previewed same-customer DRAFT or "
            "WAITING_CONFIRMATION order for deletion. May be repeated."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    db = SessionLocal()
    try:
        selector = {
            "store_id": args.store_id,
            "conversation_id": args.conversation_id,
            "psid": args.psid,
            "test_customer_id": args.test_customer_id,
        }
        if not args.execute:
            preview = preview_messenger_test_conversation_reset(db, **selector)
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            print(
                "\nDry run only. No database rows were changed. "
                "Review the IDs before executing."
            )
            return 0

        if args.psid is not None or args.test_customer_id is not None:
            raise ValueError(
                "Execution requires --conversation-id so the final operation "
                "is bound to one exact conversation."
            )

        with db.begin():
            preview = preview_messenger_test_conversation_reset(db, **selector)
            resolved_conversation_id = preview["conversation"]["id"]
            if args.confirm_conversation_id != resolved_conversation_id:
                raise ValueError(
                    "--execute requires --confirm-conversation-id to exactly "
                    f"match {resolved_conversation_id}."
                )

            selected_order_ids = set(args.delete_unconfirmed_test_order_id)
            eligible_order_ids = {
                order["id"]
                for order in preview[
                    "unconfirmed_test_orders_requiring_explicit_ids"
                ]
            }
            if not selected_order_ids.issubset(eligible_order_ids):
                raise ValueError(
                    "An order ID was not listed as an eligible unconfirmed "
                    "draft by this dry run."
                )

            result = reset_messenger_test_conversation(
                db,
                store_id=args.store_id,
                conversation_id=resolved_conversation_id,
                delete_unconfirmed_test_order_ids=sorted(selected_order_ids),
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\nReset committed.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Reset not completed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
