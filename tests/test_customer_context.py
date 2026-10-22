"""
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
from app.models.product import Product
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

    def _create_order(self, db, store_id, customer_id, status=OrderStatus.DELIVERED, amount=Decimal("100.00")):
        order = Order(
            store_id=store_id, customer_id=customer_id,
            status=status, subtotal=amount, total=amount,
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
        self._create_order(db_session, store_id, customer.id, OrderStatus.DELIVERED)
        self._create_order(db_session, store_id, customer.id, OrderStatus.DRAFT)
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        assert len(ctx["recent_orders"]) == 2

    def test_open_orders_correctly_identified(self, db_session):
        store_id = uuid.uuid4()
        customer = self._create_customer(db_session, store_id)
        self._create_order(db_session, store_id, customer.id, OrderStatus.DRAFT)
        self._create_order(db_session, store_id, customer.id, OrderStatus.CONFIRMED)
        self._create_order(db_session, store_id, customer.id, OrderStatus.DELIVERED)
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
        product = Product(
            store_id=store_id,
            name="Test Product",
            base_price=Decimal("50.00"),
            is_active=True,
        )
        db_session.add(product)
        db_session.flush()
        item = OrderItem(
            order_id=order.id, product_id=product.id,
            quantity=2, unit_price=Decimal("50.00"),
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
        self._create_order(db_session, store_id, customer.id, OrderStatus.DELIVERED, Decimal("100"))
        self._create_order(db_session, store_id, customer.id, OrderStatus.DELIVERED, Decimal("200"))
        self._create_order(db_session, store_id, customer.id, OrderStatus.CANCELLED, Decimal("50"))
        db_session.commit()
        ctx = customer_context_service.get_customer_context(db_session, store_id, customer.id)
        bs = ctx["behavior_summary"]
        assert bs["total_orders"] == 3
        assert bs["completed_orders"] == 2
        assert bs["cancelled_orders"] == 1
        assert bs["total_spent"] == "300.00"

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
