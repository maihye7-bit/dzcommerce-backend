import uuid
from decimal import Decimal

import pytest
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.registry import ToolRegistry
from app.database import Base
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.services.exceptions import NotFoundError, ValidationError
import app.agent.tools.create_order_draft as draft_tool_module


@pytest.fixture
def isolated_db(tmp_path):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "phase20c-audit.sqlite")),
    )
    statements = []
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.set_trace_callback(statements.append),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    factory.audit_statements = statements
    try:
        yield factory
    finally:
        engine.dispose()


def seed(factory, stock=5):
    with factory.begin() as db:
        store = Store(name="Synthetic audit store", slug=f"audit-{uuid.uuid4()}")
        db.add(store)
        db.flush()
        customer = Customer(store_id=store.id, name="Synthetic customer")
        db.add(customer)
        db.flush()
        conversation = Conversation(
            store_id=store.id,
            customer_id=customer.id,
            channel="audit",
            status=ConversationStatus.ACTIVE,
            metadata_json={"variant_index_map": {}},
            active_draft_json=None,
        )
        db.add(conversation)
        db.flush()
        product = Product(
            store_id=store.id,
            name="Synthetic product",
            base_price=Decimal("12.50"),
            is_active=True,
        )
        db.add(product)
        db.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Synthetic option",
            price_adjustment=Decimal("1.50"),
        )
        db.add(variant)
        db.flush()
        db.add(
            InventoryItem(
                store_id=store.id,
                variant_id=variant.id,
                quantity=stock,
            )
        )
        conversation.metadata_json = {
            "variant_index_map": {"1": str(variant.id)},
            "prior_valid_state": "preserve",
        }
        result = (store.id, conversation.id, variant.id)
    return result


def registry():
    tools = ToolRegistry()
    tools.register(CreateOrderDraftTool())
    return tools


@pytest.mark.asyncio
async def test_successful_tool_draft_is_persisted_after_session_close(isolated_db):
    store_id, conversation_id, variant_id = seed(isolated_db)
    tool_session = isolated_db()
    result = await registry().aexecute(
        tool_name="create_order_draft",
        arguments={"items": [{"variant_index": 1, "quantity": 2}]},
        context={
            "db": tool_session,
            "store_id": store_id,
            "conversation_id": conversation_id,
        },
    )
    assert result.success is True
    assert tool_session.is_active
    assert tool_session.in_transaction()
    tool_session.close()

    with isolated_db() as reader:
        conversation = reader.get(Conversation, conversation_id)
        assert conversation.active_draft_json is not None
        assert conversation.active_draft_json["items"] == [
            {
                "variant_id": str(variant_id),
                "product_name": "Synthetic product",
                "variant_name": "Synthetic option",
                "unit_price": 14.0,
                "quantity": 2,
                "line_total": 28.0,
                "available_stock": 5,
            }
        ]
        assert conversation.active_draft_json["total_price"] == 28.0
    statements = isolated_db.audit_statements
    savepoint_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith("SAVEPOINT ")
    )
    release_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith("RELEASE SAVEPOINT ")
    )
    assert savepoint_index < release_index
    assert not any(
        statement == "BEGIN"
        for statement in statements[savepoint_index:release_index]
    )


@pytest.mark.asyncio
async def test_tool_savepoint_is_not_a_commit_inside_owner_transaction(isolated_db):
    store_id, conversation_id, _variant_id = seed(isolated_db)
    tool_session = isolated_db()
    conversation = tool_session.get(Conversation, conversation_id)
    conversation.metadata_json = {
        **conversation.metadata_json,
        "uncommitted_owner_change": True,
    }
    tool_session.flush()

    result = await registry().aexecute(
        tool_name="create_order_draft",
        arguments={"items": [{"variant_index": 1, "quantity": 2}]},
        context={
            "db": tool_session,
            "store_id": store_id,
            "conversation_id": conversation_id,
        },
    )
    assert result.success is True
    tool_session.close()

    with isolated_db() as reader:
        persisted = reader.get(Conversation, conversation_id)
        assert persisted.active_draft_json is None
        assert "uncommitted_owner_change" not in persisted.metadata_json


@pytest.mark.asyncio
async def test_owner_commit_persists_tool_draft_after_session_close(isolated_db):
    store_id, conversation_id, variant_id = seed(isolated_db)
    owner_session = isolated_db()
    conversation = owner_session.get(Conversation, conversation_id)
    conversation.metadata_json = {
        **conversation.metadata_json,
        "owner_transaction_started": True,
    }
    owner_session.flush()

    result = await registry().aexecute(
        tool_name="create_order_draft",
        arguments={"items": [{"variant_index": 1, "quantity": 2}]},
        context={
            "db": owner_session,
            "store_id": store_id,
            "conversation_id": conversation_id,
        },
    )
    assert result.success is True
    owner_session.commit()
    owner_session.close()

    with isolated_db() as reader:
        persisted = reader.get(Conversation, conversation_id)
        assert persisted.metadata_json["owner_transaction_started"] is True
        assert persisted.active_draft_json["items"][0]["variant_id"] == str(variant_id)
        assert persisted.active_draft_json["total_price"] == 28.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_type", "expected_code"),
    [
        ("unknown_index", ValidationError, "VALIDATION_ERROR"),
        ("unknown_variant", ValidationError, "VALIDATION_ERROR"),
        ("no_stock", ValidationError, "VALIDATION_ERROR"),
        ("invalid_quantity", ValidationError, "VALIDATION_ERROR"),
        ("missing_conversation", NotFoundError, "NOT_FOUND"),
    ],
)
async def test_expected_draft_errors_are_classified_without_partial_write(
    isolated_db,
    case,
    expected_type,
    expected_code,
):
    store_id, conversation_id, _variant_id = seed(
        isolated_db,
        stock=0 if case == "no_stock" else 5,
    )
    session = isolated_db()
    args = {"items": [{"variant_index": 1, "quantity": 1}]}
    call_conversation_id = conversation_id
    if case == "unknown_index":
        args["items"][0]["variant_index"] = 99
    elif case == "invalid_quantity":
        args["items"][0]["quantity"] = 0
    elif case == "unknown_variant":
        conversation = session.get(Conversation, conversation_id)
        conversation.metadata_json = {
            "variant_index_map": {"1": str(uuid.uuid4())},
            "prior_valid_state": "preserve",
        }
        session.flush()
    elif case == "missing_conversation":
        call_conversation_id = uuid.uuid4()

    result = await registry().aexecute(
        tool_name="create_order_draft",
        arguments=args,
        context={
            "db": session,
            "store_id": store_id,
            "conversation_id": call_conversation_id,
        },
    )

    assert result.success is False
    assert result.error_code == expected_code
    assert result.error
    session.commit()
    session.close()
    with isolated_db() as reader:
        conversation = reader.get(Conversation, conversation_id)
        assert conversation.active_draft_json is None
        assert conversation.metadata_json["prior_valid_state"] == "preserve"


@pytest.mark.asyncio
async def test_unexpected_error_propagates_and_outer_rollback_preserves_state(
    isolated_db, monkeypatch
):
    store_id, conversation_id, _variant_id = seed(isolated_db)
    session = isolated_db()
    conversation = session.get(Conversation, conversation_id)
    conversation.metadata_json = {
        "variant_index_map": conversation.metadata_json["variant_index_map"],
        "prior_valid_state": "preserve",
        "uncommitted_turn_state": "must roll back",
    }

    def raise_unexpected(**_kwargs):
        raise RuntimeError("synthetic unexpected failure")

    monkeypatch.setattr(draft_tool_module, "save_draft_safe", raise_unexpected)
    with pytest.raises(RuntimeError, match="synthetic unexpected failure"):
        await registry().aexecute(
            tool_name="create_order_draft",
            arguments={"items": [{"variant_index": 1, "quantity": 1}]},
            context={
                "db": session,
                "store_id": store_id,
                "conversation_id": conversation_id,
            },
        )
    assert session.is_active
    session.rollback()
    session.close()

    with isolated_db() as reader:
        conversation = reader.get(Conversation, conversation_id)
        assert conversation.active_draft_json is None
        assert conversation.metadata_json["prior_valid_state"] == "preserve"
        assert "uncommitted_turn_state" not in conversation.metadata_json
