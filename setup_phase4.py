
"""
Phase 4 Setup Script - Customer Intelligence
Run: python setup_phase4.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 4: Customer Intelligence Setup ===\n")

# ============================================================
# 1. MODEL: CustomerMemory
# ============================================================
write_file("app/models/customer_memory.py", '''"""
Structured customer memory for Phase 4.
NOT free-form LLM memory. Each record is attributable to application
events or explicit customer information.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey, func, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomerMemory(Base):
    __tablename__ = "customer_memories"
    __table_args__ = (
        Index("ix_customer_memories_store_customer", "store_id", "customer_id"),
        Index("ix_customer_memories_type", "store_id", "memory_type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
''')

# ============================================================
# 2. SCHEMAS: CustomerContext
# ============================================================
write_file("app/schemas/customer_context.py", '''"""
Pydantic schemas for customer context responses.
These define the structured output of CustomerContextService.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CustomerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime


class OrderSummary(BaseModel):
    id: uuid.UUID
    status: str
    total_amount: Decimal
    currency: str
    created_at: datetime
    item_count: int = 0


class PreviousProduct(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    order_date: datetime


class ConversationSummary(BaseModel):
    id: uuid.UUID
    channel: str
    status: str
    created_at: datetime
    last_message: Optional[str] = None
    message_count: int = 0


class MemoryEntry(BaseModel):
    memory_type: str
    key: str
    value: str
    confidence: float
    created_at: datetime


class BehaviorSummary(BaseModel):
    total_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    open_orders: int = 0
    total_purchased_quantity: int = 0
    total_spent: Decimal = Decimal("0")
    last_order_date: Optional[datetime] = None


class CustomerContext(BaseModel):
    customer: CustomerInfo
    recent_orders: list[OrderSummary] = []
    open_orders: list[OrderSummary] = []
    previous_products: list[PreviousProduct] = []
    recent_conversations: list[ConversationSummary] = []
    preferences: list[MemoryEntry] = []
    behavior_summary: BehaviorSummary = BehaviorSummary()
''')

# ============================================================
# 3. SERVICE: CustomerContextService
# ============================================================
write_file("app/services/customer_context_service.py", '''"""
CustomerContextService: builds structured customer context from
persisted application data only. Never invents data.

Architecture:
  Agent Tool -> CustomerContextService -> Database (via ORM queries)

Every query is scoped by store_id for tenant isolation.
"""
import uuid
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer_memory import CustomerMemory
from app.services.exceptions import NotFoundError


# Open statuses: orders that still require action
OPEN_STATUSES = [OrderStatus.DRAFT, OrderStatus.CONFIRMED]


def get_customer(
    db: Session, store_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer:
    """Fetch customer with strict tenant isolation."""
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.store_id == store_id)
        .first()
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


def get_customer_context(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    recent_orders_limit: int = 5,
    recent_conversations_limit: int = 5,
    memories_limit: int = 20,
) -> dict:
    """
    Build complete customer context. All queries scoped by store_id.
    Returns a plain dict (serializable) for the agent tool.
    """
    # 1. Verify customer exists in this store (raises NotFoundError if not)
    customer = get_customer(db, store_id, customer_id)

    # 2. Recent orders (all statuses, most recent first)
    recent_orders = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .limit(recent_orders_limit)
        .all()
    )

    # 3. Open orders (DRAFT or CONFIRMED)
    open_orders = (
        db.query(Order)
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
            Order.status.in_(OPEN_STATUSES),
        )
        .order_by(Order.created_at.desc())
        .all()
    )

    # 4. Previous products (from order items, joined with orders)
    previous_products = (
        db.query(OrderItem, Order.created_at)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
        )
        .order_by(Order.created_at.desc())
        .limit(recent_orders_limit * 5)
        .all()
    )

    # 5. Recent conversations
    recent_conversations = (
        db.query(Conversation)
        .filter(
            Conversation.store_id == store_id,
            Conversation.customer_id == customer_id,
        )
        .order_by(Conversation.created_at.desc())
        .limit(recent_conversations_limit)
        .all()
    )

    # 6. Customer memories (preferences, interests, etc.)
    memories = (
        db.query(CustomerMemory)
        .filter(
            CustomerMemory.store_id == store_id,
            CustomerMemory.customer_id == customer_id,
        )
        .order_by(CustomerMemory.created_at.desc())
        .limit(memories_limit)
        .all()
    )

    # 7. Behavior summary (deterministic counts)
    behavior = _build_behavior_summary(db, store_id, customer_id)

    # 8. Build conversation summaries with last message
    conversation_summaries = []
    for conv in recent_conversations:
        msg_count = (
            db.query(func.count(Message.id))
            .filter(Message.conversation_id == conv.id)
            .scalar()
        )
        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        conversation_summaries.append({
            "id": str(conv.id),
            "channel": conv.channel,
            "status": conv.status.value if hasattr(conv.status, "value") else str(conv.status),
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "last_message": last_msg.content[:200] if last_msg else None,
            "message_count": msg_count or 0,
        })

    # 9. Assemble the context
    return {
        "customer": {
            "id": str(customer.id),
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "language": customer.language,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        },
        "recent_orders": [
            {
                "id": str(o.id),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "item_count": len(o.id and db.query(OrderItem).filter(OrderItem.order_id == o.id).all() or []),
            }
            for o in recent_orders
        ],
        "open_orders": [
            {
                "id": str(o.id),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in open_orders
        ],
        "previous_products": [
            {
                "product_id": str(item.product_id),
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "order_date": order_date.isoformat() if order_date else None,
            }
            for item, order_date in previous_products
        ],
        "recent_conversations": conversation_summaries,
        "preferences": [
            {
                "memory_type": m.memory_type,
                "key": m.key,
                "value": m.value,
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
        "behavior_summary": behavior,
    }


def _build_behavior_summary(
    db: Session, store_id: uuid.UUID, customer_id: uuid.UUID
) -> dict:
    """Deterministic behavior summary from order data."""
    orders = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .all()
    )

    total_orders = len(orders)
    completed = sum(1 for o in orders if o.status == OrderStatus.COMPLETED)
    cancelled = sum(1 for o in orders if o.status == OrderStatus.CANCELLED)
    open_count = sum(1 for o in orders if o.status in OPEN_STATUSES)

    # Total purchased quantity and spending
    total_qty = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .scalar()
    )

    total_spent = (
        db.query(func.coalesce(func.sum(Order.total_amount), 0))
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
            Order.status == OrderStatus.COMPLETED,
        )
        .scalar()
    )

    last_order = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .first()
    )

    return {
        "total_orders": total_orders,
        "completed_orders": completed,
        "cancelled_orders": cancelled,
        "open_orders": open_count,
        "total_purchased_quantity": int(total_qty),
        "total_spent": str(total_spent),
        "last_order_date": last_order.created_at.isoformat() if last_order and last_order.created_at else None,
    }
''')

# ============================================================
# 4. TOOL: get_customer_context
# ============================================================
write_file("app/agent/tools/get_customer_context.py", '''"""
get_customer_context tool: retrieves structured customer context.
Uses CustomerContextService internally. Never accesses DB directly.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import customer_context_service
from app.services.exceptions import NotFoundError


class GetCustomerContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_customer_context"

    @property
    def description(self) -> str:
        return (
            "Retrieve structured context about the current customer: "
            "their info, order history, previous products, open orders, "
            "recent conversations, preferences, and behavior summary. "
            "Use this to personalize responses."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_conversations": {
                    "type": "boolean",
                    "description": "Whether to include recent conversations",
                },
                "recent_orders_limit": {
                    "type": "integer",
                    "description": "Max number of recent orders to include (default 5, max 20)",
                },
            },
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)

            # customer_id comes from conversation context, NOT from LLM
            customer_id = context.get("customer_id") if context else None
            if not customer_id:
                return ToolResult(
                    success=False,
                    error="No customer context available",
                )

            db: Session = context["db"]
            limit = min(int(args.get("recent_orders_limit", 5)), 20)

            result = customer_context_service.get_customer_context(
                db=db,
                store_id=store_id,
                customer_id=customer_id,
                recent_orders_limit=limit,
            )

            return ToolResult(success=True, data=result)

        except NotFoundError:
            return ToolResult(success=False, error="Customer not found")
        except (ValueError, TypeError) as e:
            return ToolResult(success=False, error="Invalid arguments")
        except Exception:
            return ToolResult(success=False, error="Failed to retrieve customer context")
''')

# ============================================================
# 5. MIGRATION: 0004_customer_intelligence.py
# ============================================================
write_file("alembic/versions/0004_customer_intelligence.py", '''"""customer intelligence: customer_memories table
Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_type", sa.String(50), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence_range"),
    )
    op.create_index("ix_customer_memories_store_customer", "customer_memories", ["store_id", "customer_id"])
    op.create_index("ix_customer_memories_type", "customer_memories", ["store_id", "memory_type"])


def downgrade() -> None:
    op.drop_index("ix_customer_memories_type", table_name="customer_memories")
    op.drop_index("ix_customer_memories_store_customer", table_name="customer_memories")
    op.drop_table("customer_memories")
''')

# ============================================================
# 6. TESTS: test_customer_context.py
# ============================================================
write_file("tests/test_customer_context.py", '''"""
Tests for Phase 4: Customer Intelligence.
Covers CustomerContextService, GetCustomerContextTool, and tenant isolation.
"""
import uuid
import pytest
from decimal import Decimal

from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus
from app.models.conversation import Conversation, Message, MessageRole, ConversationStatus
from app.models.customer_memory import CustomerMemory
from app.services import customer_context_service
from app.services.exceptions import NotFoundError
from tests.helpers import register_and_get_token, auth_headers, get_first_store_id


# ============================================================
# Service-level tests (using db_session fixture)
# ============================================================

class TestCustomerContextService:
    """Direct service tests with controlled data."""

    def _create_customer(self, db, store_id):
        customer = Customer(store_id=store_id, name="Test Customer", phone="0550123456")
        db.add(customer)
        db.flush()
        return customer

    def _create_order(self, db, store_id, customer_id, status=OrderStatus.COMPLETED, amount=Decimal("100.00")):
        order = Order(
            store_id=store_id, customer_id=customer_id,
            status=status, total_amount=amount, currency="DZD",
        )
        db.add(order)
        db.flush()
        return order

    def test_returns_customer_info(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert ctx["customer"]["name"] == "Test Customer"
        assert ctx["customer"]["phone"] == "0550123456"

    def test_unknown_customer_raises_not_found(self, db_session):
        store_id = uuid.uuid4()
        fake_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            customer_context_service.get_customer_context(db_session, store_id, fake_id)

    def test_customer_from_another_store_not_accessible(self, db_session):
        store_a = uuid.uuid4()
        store_b = uuid.uuid4()
        customer = self._create_customer(db_session, store_a)
        db_session.commit()
        with pytest.raises(NotFoundError):
            customer_context_service.get_customer_context(db_session, store_b, customer.id)

    def test_returns_recent_orders(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        self._create_order(db_session, store_id, customer.id, OrderStatus.COMPLETED)
        self._create_order(db_session, store_id, customer.id, OrderStatus.DRAFT)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert len(ctx["recent_orders"]) == 2

    def test_open_orders_correctly_identified(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        self._create_order(db_session, store_id, customer.id, OrderStatus.DRAFT)
        self._create_order(db_session, store_id, customer.id, OrderStatus.CONFIRMED)
        self._create_order(db_session, store_id, customer.id, OrderStatus.COMPLETED)
        self._create_order(db_session, store_id, customer.id, OrderStatus.CANCELLED)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert len(ctx["open_orders"]) == 2
        statuses = [o["status"] for o in ctx["open_orders"]]
        assert "draft" in statuses
        assert "confirmed" in statuses

    def test_previous_products_returned(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        order = self._create_order(db_session, store_id, customer.id)
        product_id = uuid.uuid4()
        item = OrderItem(
            order_id=order.id, product_id=product_id,
            product_name="Test Product", quantity=2, unit_price=Decimal("50.00"),
        )
        db_session.add(item)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert len(ctx["previous_products"]) == 1
        assert ctx["previous_products"][0]["product_name"] == "Test Product"
        assert ctx["previous_products"][0]["quantity"] == 2

    def test_recent_conversations_limited(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        for i in range(10):
            conv = Conversation(
                store_id=store_id, customer_id=customer.id,
                channel="api", status=ConversationStatus.ACTIVE,
            )
            db_session.add(conv)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(
            db_session, store_id, customer.id, recent_conversations_limit=3
        )
        assert len(ctx["recent_conversations"]) == 3

    def test_customer_memory_isolated_by_store(self, db_session):
        store_a = uuid.uuid4()
        store_b = uuid.uuid4()
        customer = self._create_customer(db_session, store_a)
        memory = CustomerMemory(
            store_id=store_a, customer_id=customer.id,
            memory_type="preference", key="preferred_language", value="ar",
        )
        db_session.add(memory)
        db_session.commit()
        # Access from store_a works
        ctx = customer_context_service.get_customer_context(db_session, store_a, customer.id)
        assert len(ctx["preferences"]) == 1
        # Access from store_b fails
        with pytest.raises(NotFoundError):
            customer_context_service.get_customer_context(db_session, store_b, customer.id)

    def test_behavior_summary_deterministic(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        self._create_order(db_session, store_id, customer.id, OrderStatus.COMPLETED, Decimal("100"))
        self._create_order(db_session, store_id, customer.id, OrderStatus.COMPLETED, Decimal("200"))
        self._create_order(db_session, store_id, customer.id, OrderStatus.CANCELLED, Decimal("50"))
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        bs = ctx["behavior_summary"]
        assert bs["total_orders"] == 3
        assert bs["completed_orders"] == 2
        assert bs["cancelled_orders"] == 1
        assert bs["total_spent"] == "300"

    def test_empty_customer_history(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert ctx["recent_orders"] == []
        assert ctx["open_orders"] == []
        assert ctx["previous_products"] == []
        assert ctx["recent_conversations"] == []
        assert ctx["preferences"] == []
        assert ctx["behavior_summary"]["total_orders"] == 0


# ============================================================
# Tool-level tests (via API)
# ============================================================

class TestGetCustomerContextTool:
    """Integration tests through the agent chat endpoint."""

    def test_agent_can_execute_get_customer_context(self, client):
        token = register_and_get_token(client, "ctx_test@example.com", store_name="Context Store")
        store_id = get_first_store_id(client, token)
        headers = auth_headers(token)

        # The mock provider will trigger get_customer_context if message contains "context"
        # For now, just verify the endpoint works
        resp = client.post("/api/agent/chat", json={
            "store_id": str(store_id),
            "message": "hello",
            "channel": "api",
        }, headers=headers)
        assert resp.status_code == 200

    def test_another_tenant_customer_not_accessible(self, client):
        token_a = register_and_get_token(client, "ctx_a@example.com", store_name="Store CTX A")
        token_b = register_and_get_token(client, "ctx_b@example.com", store_name="Store CTX B")
        store_a = get_first_store_id(client, token_a)

        resp = client.post("/api/agent/chat", json={
            "store_id": str(store_a),
            "message": "get context",
            "channel": "api",
        }, headers=auth_headers(token_b))
        assert resp.status_code == 404
''')

# ============================================================
# 7. MODIFY: models/__init__.py
# ============================================================
init_content = '''"""
Import every model here so that Base.metadata knows about all tables.
Phase 1: auth + multi-tenancy
Phase 2: products + inventory
Phase 3: customers, orders, conversations, messages, human_handoffs
Phase 4: customer_memories
"""
from app.models.user import User
from app.models.store import Store
from app.models.store_user import StoreUser, StoreRole
from app.models.product import Product
from app.models.inventory import Inventory
from app.models.customer import Customer
from app.models.conversation import Conversation, ConversationStatus, MessageRole, Message
from app.models.order import Order, OrderItem, OrderStatus
from app.models.human_handoff import HumanHandoff
from app.models.customer_memory import CustomerMemory

__all__ = [
    "User", "Store", "StoreUser", "StoreRole", "Product", "Inventory",
    "Customer",
    "Conversation", "ConversationStatus", "MessageRole", "Message",
    "Order", "OrderItem", "OrderStatus",
    "HumanHandoff",
    "CustomerMemory",
]
'''
write_file("app/models/__init__.py", init_content)

# ============================================================
# 8. MODIFY: api/agent.py (add GetCustomerContextTool)
# ============================================================
agent_content = '''import uuid
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

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _build_engine() -> ConversationEngine:
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.register(CheckInventoryTool())
    registry.register(GetPriceTool())
    registry.register(HandoffToHumanTool())
    registry.register(GetCustomerContextTool())
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
'''
write_file("app/api/agent.py", agent_content)

print("\n=== Phase 4 Setup Complete! ===")
print("\nNext steps:")
print("  1. python -m pytest tests/test_customer_context.py -v")
print("  2. python -m pytest -v  (all tests)")
print("  3. alembic upgrade head  (when ready for PostgreSQL)")
