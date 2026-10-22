"""
Phase 13.4 persistence probe.

Run this BEFORE applying the model fix, then AFTER applying it.

It uses the actual Conversation model and proves whether in-place JSON
mutations survive across a NEW SQLAlchemy Session.
"""

import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.conversation import Conversation


def main() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Conversation.__table__.create(engine)

    SessionLocal = sessionmaker(bind=engine, future=True)

    conversation_id = uuid.uuid4()
    store_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    # --------------------------------------------------------------
    # Session A: create conversation with initial metadata_json
    # --------------------------------------------------------------
    session_a = SessionLocal()
    conv = Conversation(
        id=conversation_id,
        store_id=store_id,
        customer_id=customer_id,
        channel="probe",
        status="active",
        metadata_json={"a": 1},
        active_draft_json=None,
    )
    session_a.add(conv)
    session_a.commit()
    session_a.close()

    # --------------------------------------------------------------
    # Session B: mutate metadata_json IN PLACE using exact app patterns
    # --------------------------------------------------------------
    session_b = SessionLocal()
    conv = session_b.get(Conversation, conversation_id)

    # search_products-like pattern
    if conv.metadata_json is None:
        conv.metadata_json = {}

    conv.metadata_json["last_searched_product"] = {
        "id": "fake-product-id-for-persistence-probe",
        "name": "Nike Air Max",
    }

    conv.metadata_json.pop("selected_variant_id", None)

    # get_product_details-like pattern
    if conv.metadata_json is None:
        conv.metadata_json = {}

    conv.metadata_json["variant_index_map"] = {
        "1": "11111111-1111-1111-1111-111111111111",
        "2": "22222222-2222-2222-2222-222222222222",
    }

    conv.metadata_json["last_product_id"] = "fake-product-id-for-persistence-probe"

    session_b.commit()
    session_b.close()

    # --------------------------------------------------------------
    # Session C: NEW session, reload from DB
    # --------------------------------------------------------------
    session_c = SessionLocal()
    conv = session_c.get(Conversation, conversation_id)

    print("BEFORE/AFTER FIX PROBE")
    print("conversation_id:", conversation_id)
    print("metadata_json after reload:", conv.metadata_json)

    expected_keys = {
        "a",
        "last_searched_product",
        "variant_index_map",
        "last_product_id",
    }

    actual_keys = set((conv.metadata_json or {}).keys())

    print("expected_keys:", sorted(expected_keys))
    print("actual_keys:", sorted(actual_keys))

    missing = expected_keys - actual_keys
    if missing:
        print("RESULT: FAIL - in-place mutation did NOT persist across NEW session.")
        print("missing_keys:", sorted(missing))
    else:
        print("RESULT: PASS - in-place mutation persisted across NEW session.")

    session_c.close()

    # --------------------------------------------------------------
    # active_draft_json assignment and clearing
    # --------------------------------------------------------------
    session_d = SessionLocal()
    conv = session_d.get(Conversation, conversation_id)
    conv.active_draft_json = {
        "items": [
            {
                "variant_id": "11111111-1111-1111-1111-111111111111",
                "product_name": "Nike Air Max",
                "variant_name": "Black / 42",
                "quantity": 1,
                "unit_price": 8500.0,
                "line_total": 8500.0,
            }
        ],
        "total_price": 8500.0,
        "currency": "DZD",
    }
    session_d.commit()
    session_d.close()

    session_e = SessionLocal()
    conv = session_e.get(Conversation, conversation_id)
    print("active_draft_json after assignment reload:", conv.active_draft_json)
    session_e.close()

    session_f = SessionLocal()
    conv = session_f.get(Conversation, conversation_id)
    conv.active_draft_json = None
    session_f.commit()
    session_f.close()

    session_g = SessionLocal()
    conv = session_g.get(Conversation, conversation_id)
    print("active_draft_json after clear reload:", conv.active_draft_json)
    session_g.close()


if __name__ == "__main__":
    main()
