"""
Phase 5 Part 3 - Agent Tools + Tests
Run: python setup_phase5_part3.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 5 Part 3: Agent Tools + Tests ===\n")

# ============================================================
# 1. TOOL: create_order_draft
# ============================================================
write_file("app/agent/tools/create_order_draft.py", '''"""
create_order_draft tool: creates a new order draft for the current customer.
Does NOT touch inventory. The draft remains modifiable until confirmed.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service


class CreateOrderDraftTool(BaseTool):
    @property
    def name(self) -> str:
        return "create_order_draft"

    @property
    def description(self) -> str:
        return (
            "Create a new order draft for the current customer. "
            "The draft is empty and must have items added before confirmation. "
            "Creating a draft does NOT reserve stock or finalize the sale."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            customer_id = context.get("customer_id") if context else None
            if not customer_id:
                return ToolResult(success=False, error="No customer context available")

            db: Session = context["db"]
            conversation_id = context.get("conversation_id")

            order = order_service.create_draft(
                db=db,
                store_id=store_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
            )

            return ToolResult(success=True, data={
                "order_id": str(order.id),
                "status": order.status.value,
                "total_amount": str(order.total_amount),
                "message": "Order draft created. Add items before confirming.",
            })
        except Exception:
            return ToolResult(success=False, error="Failed to create order draft")
''')

# ============================================================
# 2. TOOL: add_item_to_order
# ============================================================
write_file("app/agent/tools/add_item_to_order.py", '''"""
add_item_to_order tool: adds a product to an order draft.
Price is ALWAYS taken from the authoritative product record.
The Agent can NEVER override the price.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import (
    NotFoundError,
    OrderNotModifiableError,
)


class AddItemToOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "add_item_to_order"

    @property
    def description(self) -> str:
        return (
            "Add a product to an order draft. "
            "The price is always taken from the product catalog - "
            "you cannot set or override the price. "
            "Only works on DRAFT orders."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "UUID of the order draft"},
                "product_id": {"type": "string", "description": "UUID of the product to add"},
                "quantity": {"type": "integer", "description": "Quantity (must be positive)", "minimum": 1},
            },
            "required": ["order_id", "product_id", "quantity"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]

            order_id = uuid.UUID(args["order_id"])
            product_id = uuid.UUID(args["product_id"])
            quantity = int(args["quantity"])

            item = order_service.add_item(
                db=db,
                store_id=store_id,
                order_id=order_id,
                product_id=product_id,
                quantity=quantity,
            )

            return ToolResult(success=True, data={
                "item_id": str(item.id),
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "message": f"Added {item.quantity} x {item.product_name}",
            })

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except OrderNotModifiableError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError) as e:
            return ToolResult(success=False, error="Invalid arguments")
        except Exception:
            return ToolResult(success=False, error="Failed to add item to order")
''')

# ============================================================
# 3. TOOL: get_order
# ============================================================
write_file("app/agent/tools/get_order.py", '''"""
get_order tool: retrieves order details including items and totals.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import NotFoundError
from app.models.order import OrderItem


class GetOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_order"

    @property
    def description(self) -> str:
        return (
            "Get the details of an order including its items, quantities, "
            "prices, total, and current status."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "UUID of the order"},
            },
            "required": ["order_id"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]
            order_id = uuid.UUID(args["order_id"])

            order = order_service.get_order(db, store_id, order_id)
            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()

            return ToolResult(success=True, data={
                "order_id": str(order.id),
                "status": order.status.value,
                "total_amount": str(order.total_amount),
                "currency": order.currency,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "items": [
                    {
                        "item_id": str(item.id),
                        "product_name": item.product_name,
                        "quantity": item.quantity,
                        "unit_price": str(item.unit_price),
                        "subtotal": str(item.unit_price * item.quantity),
                    }
                    for item in items
                ],
            })

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid order_id format")
        except Exception:
            return ToolResult(success=False, error="Failed to get order")
''')

# ============================================================
# 4. TOOL: confirm_order
# ============================================================
write_file("app/agent/tools/confirm_order.py", '''"""
confirm_order tool: confirms a draft order.
This is a critical transaction that validates inventory and
atomically decrements stock. Idempotent against duplicate calls.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import (
    NotFoundError,
    OrderStateError,
    InsufficientInventoryError,
)


class ConfirmOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "confirm_order"

    @property
    def description(self) -> str:
        return (
            "Confirm an order draft. This validates that sufficient stock "
            "is available and atomically decrements inventory. "
            "Only call this after explicit customer confirmation. "
            "This action is idempotent - calling it twice is safe."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "UUID of the order to confirm"},
            },
            "required": ["order_id"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]
            order_id = uuid.UUID(args["order_id"])

            order = order_service.confirm_order(db, store_id, order_id)

            return ToolResult(success=True, data={
                "order_id": str(order.id),
                "status": order.status.value,
                "total_amount": str(order.total_amount),
                "message": "Order confirmed successfully. Inventory updated.",
            })

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except OrderStateError as e:
            return ToolResult(success=False, error=str(e))
        except InsufficientInventoryError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid order_id format")
        except Exception:
            return ToolResult(success=False, error="Failed to confirm order")
''')

# ============================================================
# 5. TOOL: cancel_order
# ============================================================
write_file("app/agent/tools/cancel_order.py", '''"""
cancel_order tool: cancels an order.
Only allowed from DRAFT or CONFIRMED states.
If confirmed, restores inventory.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import order_service
from app.services.exceptions import NotFoundError, OrderStateError


class CancelOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "cancel_order"

    @property
    def description(self) -> str:
        return (
            "Cancel an order. Only allowed from DRAFT or CONFIRMED states. "
            "If the order was already confirmed, inventory will be restored. "
            "This action is idempotent."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "UUID of the order to cancel"},
            },
            "required": ["order_id"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]
            order_id = uuid.UUID(args["order_id"])

            order = order_service.cancel_order(db, store_id, order_id)

            return ToolResult(success=True, data={
                "order_id": str(order.id),
                "status": order.status.value,
                "message": "Order cancelled.",
            })

        except NotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except OrderStateError as e:
            return ToolResult(success=False, error=str(e))
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid order_id format")
        except Exception:
            return ToolResult(success=False, error="Failed to cancel order")
''')

# ============================================================
# 6. UPDATE api/agent.py - Register new tools
# ============================================================
write_file("app/api/agent.py", '''import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.store_user import StoreUser
from app.models.customer import Customer
from app.schemas.conversation import AgentChatRequest, AgentChatResponse, ToolCallInfo
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.get_price import GetPriceTool
from app.agent.tools.handoff_to_human import HandoffToHumanTool
from app.agent.tools.get_customer_context import GetCustomerContextTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.add_item_to_order import AddItemToOrderTool
from app.agent.tools.get_order import GetOrderTool
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.cancel_order import CancelOrderTool

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _build_engine() -> ConversationEngine:
    registry = ToolRegistry()
    # Phase 3 tools
    registry.register(SearchProductsTool())
    registry.register(CheckInventoryTool())
    registry.register(GetPriceTool())
    registry.register(HandoffToHumanTool())
    # Phase 4 tools
    registry.register(GetCustomerContextTool())
    # Phase 5 tools
    registry.register(CreateOrderDraftTool())
    registry.register(AddItemToOrderTool())
    registry.register(GetOrderTool())
    registry.register(ConfirmOrderTool())
    registry.register(CancelOrderTool())
    return ConversationEngine(MockLLMProvider(), registry)


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        store_id = uuid.UUID(payload.store_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    membership = (
        db.query(StoreUser)
        .filter(StoreUser.store_id == store_id, StoreUser.user_id == current_user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    customer = None
    if payload.customer_external_id:
        customer = db.query(Customer).filter(
            Customer.store_id == store_id, Customer.external_id == payload.customer_external_id
        ).first()
    if not customer:
        customer = Customer(store_id=store_id, external_id=payload.customer_external_id, name="API Customer")
        db.add(customer)
        db.flush()

    engine = _build_engine()
    result = await engine.process_message(
        db=db, store_id=store_id, customer_id=customer.id,
        conversation_id=uuid.UUID(payload.conversation_id) if payload.conversation_id else None,
        channel=payload.channel,
        user_message=payload.message,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return AgentChatResponse(
        response=result["response"],
        conversation_id=uuid.UUID(result["conversation_id"]),
        handoff=result["handoff"],
        tool_calls=[ToolCallInfo(**tc) for tc in result.get("tool_calls", [])],
    )
''')

# ============================================================
# 7. TESTS: test_order_service.py
# ============================================================
write_file("tests/test_order_service.py", '''"""
Tests for Phase 5: OrderService.
Covers state machine, inventory, idempotency, tenant isolation.
"""
import uuid
import pytest
from decimal import Decimal

from app.models.customer import Customer
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.order import Order, OrderItem, OrderStatus
from app.services import order_service
from app.services.exceptions import (
    NotFoundError,
    OrderStateError,
    InsufficientInventoryError,
    OrderNotModifiableError,
)


def _make_store_customer(db):
    """Create a store and customer for testing."""
    store_id = uuid.uuid4()
    customer = Customer(store_id=store_id, name="Test Customer")
    db.add(customer)
    db.flush()
    return store_id, customer.id


def _make_product(db, store_id, name="Test Product", price=Decimal("100.00"), qty=10):
    """Create a product with inventory for testing."""
    product = Product(store_id=store_id, name=name, price=price)
    db.add(product)
    db.flush()
    inv = Inventory(store_id=store_id, product_id=product.id, quantity=qty)
    db.add(inv)
    db.flush()
    return product.id


# ============================================================
# DRAFT TESTS
# ============================================================

class TestOrderDraft:
    def test_create_draft(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        assert order.status == OrderStatus.DRAFT
        assert order.store_id == store_id
        assert order.customer_id == customer_id
        assert order.total_amount == Decimal("0")

    def test_draft_belongs_to_correct_store(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        assert order.store_id == store_id

    def test_empty_draft_handled(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        # Confirming empty draft should fail
        with pytest.raises(OrderStateError):
            order_service.confirm_order(db_session, store_id, order.id)


# ============================================================
# ITEM TESTS
# ============================================================

class TestOrderItems:
    def test_add_product(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id)
        order = order_service.create_draft(db_session, store_id, customer_id)
        item = order_service.add_item(db_session, store_id, order.id, product_id, 2)
        assert item.quantity == 2
        assert item.product_id == product_id

    def test_authoritative_price_used(self, db_session):
        """Agent cannot override the price - it comes from product catalog."""
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, price=Decimal("500.00"))
        order = order_service.create_draft(db_session, store_id, customer_id)
        item = order_service.add_item(db_session, store_id, order.id, product_id, 1)
        # Price must be the product's price, NOT anything the Agent sent
        assert item.unit_price == Decimal("500.00")

    def test_update_quantity(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id)
        order = order_service.create_draft(db_session, store_id, customer_id)
        item = order_service.add_item(db_session, store_id, order.id, product_id, 1)
        updated = order_service.update_item(db_session, store_id, order.id, item.id, 5)
        assert updated.quantity == 5

    def test_remove_item(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id)
        order = order_service.create_draft(db_session, store_id, customer_id)
        item = order_service.add_item(db_session, store_id, order.id, product_id, 1)
        order_service.remove_item(db_session, store_id, order.id, item.id)
        remaining = db_session.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        assert len(remaining) == 0

    def test_invalid_product_rejected(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        fake_product_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            order_service.add_item(db_session, store_id, order.id, fake_product_id, 1)

    def test_product_from_another_store_rejected(self, db_session):
        store_a, customer_a = _make_store_customer(db_session)
        store_b, _ = _make_store_customer(db_session)
        product_in_b = _make_product(db_session, store_b)
        order = order_service.create_draft(db_session, store_a, customer_a)
        with pytest.raises(NotFoundError):
            order_service.add_item(db_session, store_a, order.id, product_in_b, 1)

    def test_invalid_quantity_rejected(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id)
        order = order_service.create_draft(db_session, store_id, customer_id)
        with pytest.raises(ValueError):
            order_service.add_item(db_session, store_id, order.id, product_id, 0)

    def test_cannot_modify_confirmed_order(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 1)
        order_service.confirm_order(db_session, store_id, order.id)
        # Now try to add item to confirmed order -> should fail
        with pytest.raises(OrderNotModifiableError):
            order_service.add_item(db_session, store_id, order.id, product_id, 1)


# ============================================================
# TOTAL CALCULATION TESTS
# ============================================================

class TestOrderTotals:
    def test_single_item_total(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, price=Decimal("100.00"))
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 3)
        db_session.refresh(order)
        assert order.total_amount == Decimal("300.00")

    def test_multiple_items_total(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        p1 = _make_product(db_session, store_id, name="P1", price=Decimal("100.00"))
        p2 = _make_product(db_session, store_id, name="P2", price=Decimal("50.00"))
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, p1, 2)
        order_service.add_item(db_session, store_id, order.id, p2, 3)
        db_session.refresh(order)
        assert order.total_amount == Decimal("350.00")


# ============================================================
# INVENTORY TESTS
# ============================================================

class TestOrderInventory:
    def test_draft_does_not_decrement_stock(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 5)
        # Stock should still be 10 (draft doesn't decrement)
        inv = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inv.quantity == 10

    def test_confirm_decrements_stock(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 3)
        order_service.confirm_order(db_session, store_id, order.id)
        inv = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inv.quantity == 7

    def test_insufficient_inventory_rejects_confirm(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=2)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 5)
        with pytest.raises(InsufficientInventoryError):
            order_service.confirm_order(db_session, store_id, order.id)
        # Stock must NOT have changed
        inv = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inv.quantity == 2

    def test_failed_confirm_leaves_consistent_state(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=1)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 5)
        try:
            order_service.confirm_order(db_session, store_id, order.id)
        except InsufficientInventoryError:
            pass
        # Order must still be DRAFT (not partially confirmed)
        db_session.refresh(order)
        assert order.status == OrderStatus.DRAFT


# ============================================================
# STATE MACHINE TESTS
# ============================================================

class TestOrderStateMachine:
    def _confirmed_order(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 1)
        order_service.confirm_order(db_session, store_id, order.id)
        return store_id, order.id

    def test_valid_transitions(self, db_session):
        store_id, order_id = self._confirmed_order(db_session)
        order = order_service.transition_status(db_session, store_id, order_id, OrderStatus.PROCESSING)
        assert order.status == OrderStatus.PROCESSING
        order = order_service.transition_status(db_session, store_id, order_id, OrderStatus.SHIPPED)
        assert order.status == OrderStatus.SHIPPED
        order = order_service.transition_status(db_session, store_id, order_id, OrderStatus.DELIVERED)
        assert order.status == OrderStatus.DELIVERED

    def test_invalid_transition_rejected(self, db_session):
        store_id, order_id = self._confirmed_order(db_session)
        with pytest.raises(OrderStateError):
            order_service.transition_status(db_session, store_id, order_id, OrderStatus.DRAFT)

    def test_delivered_cannot_be_cancelled(self, db_session):
        store_id, order_id = self._confirmed_order(db_session)
        order_service.transition_status(db_session, store_id, order_id, OrderStatus.PROCESSING)
        order_service.transition_status(db_session, store_id, order_id, OrderStatus.SHIPPED)
        order_service.transition_status(db_session, store_id, order_id, OrderStatus.DELIVERED)
        with pytest.raises(OrderStateError):
            order_service.cancel_order(db_session, store_id, order_id)

    def test_cancel_draft(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        cancelled = order_service.cancel_order(db_session, store_id, order.id)
        assert cancelled.status == OrderStatus.CANCELLED

    def test_cancel_confirmed_restores_inventory(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 3)
        order_service.confirm_order(db_session, store_id, order.id)
        # Stock should be 7 now
        inv = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inv.quantity == 7
        # Cancel -> stock restored
        order_service.cancel_order(db_session, store_id, order.id)
        db_session.refresh(inv)
        assert inv.quantity == 10


# ============================================================
# IDEMPOTENCY TESTS
# ============================================================

class TestOrderIdempotency:
    def test_confirm_already_confirmed_is_safe(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        product_id = _make_product(db_session, store_id, qty=10)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.add_item(db_session, store_id, order.id, product_id, 2)
        order_service.confirm_order(db_session, store_id, order.id)
        # Confirm again -> should be idempotent
        order2 = order_service.confirm_order(db_session, store_id, order.id)
        assert order2.status == OrderStatus.CONFIRMED
        # Stock must NOT be decremented twice
        inv = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inv.quantity == 8  # Only decremented once

    def test_cancel_already_cancelled_is_safe(self, db_session):
        store_id, customer_id = _make_store_customer(db_session)
        order = order_service.create_draft(db_session, store_id, customer_id)
        order_service.cancel_order(db_session, store_id, order.id)
        order2 = order_service.cancel_order(db_session, store_id, order.id)
        assert order2.status == OrderStatus.CANCELLED


# ============================================================
# TENANT ISOLATION TESTS
# ============================================================

class TestOrderTenantIsolation:
    def test_store_a_cannot_read_store_b_order(self, db_session):
        store_a, customer_a = _make_store_customer(db_session)
        store_b, customer_b = _make_store_customer(db_session)
        order_b = order_service.create_draft(db_session, store_b, customer_b)
        with pytest.raises(NotFoundError):
            order_service.get_order(db_session, store_a, order_b.id)

    def test_store_a_cannot_confirm_store_b_order(self, db_session):
        store_a, customer_a = _make_store_customer(db_session)
        store_b, customer_b = _make_store_customer(db_session)
        product_b = _make_product(db_session, store_b)
        order_b = order_service.create_draft(db_session, store_b, customer_b)
        order_service.add_item(db_session, store_b, order_b.id, product_b, 1)
        with pytest.raises(NotFoundError):
            order_service.confirm_order(db_session, store_a, order_b.id)

    def test_store_a_cannot_cancel_store_b_order(self, db_session):
        store_a, customer_a = _make_store_customer(db_session)
        store_b, customer_b = _make_store_customer(db_session)
        order_b = order_service.create_draft(db_session, store_b, customer_b)
        with pytest.raises(NotFoundError):
            order_service.cancel_order(db_session, store_a, order_b.id)
''')

print("\n=== Part 3 Complete ===")
print("Agent Tools + Tests created.")
print("\nNext: Run tests with:")
print("  python -m pytest tests/test_order_service.py -v")
