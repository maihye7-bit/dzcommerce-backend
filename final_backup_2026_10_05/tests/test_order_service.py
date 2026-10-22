"""
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
