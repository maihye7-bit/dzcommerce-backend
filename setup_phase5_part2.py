"""
Phase 5 Part 2 - OrderService + Exceptions
Run: python setup_phase5_part2.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 5 Part 2: OrderService ===\n")

# ============================================================
# 1. UPDATE EXCEPTIONS
# ============================================================
write_file("app/services/exceptions.py", '''"""
Service-layer exceptions for business logic errors.
"""


class ServiceError(Exception):
    """Base class for all service-layer (business logic) errors."""


class NotFoundError(ServiceError):
    """Raised when a requested resource does not exist, or does not
    belong to the store it was requested under."""


class DuplicateSKUError(ServiceError):
    """Raised when a product SKU is already used by another product in
    the same store."""


class ValidationError(ServiceError):
    """Raised for business-rule violations not already caught by the
    Pydantic schema layer."""


# Phase 5: Order-specific exceptions

class OrderStateError(ServiceError):
    """Raised when an invalid order state transition is attempted."""


class InsufficientInventoryError(ServiceError):
    """Raised when there is not enough stock to fulfill an order."""


class OrderNotModifiableError(ServiceError):
    """Raised when trying to modify an order that is no longer in DRAFT state."""
''')

# ============================================================
# 2. ORDER SERVICE
# ============================================================
write_file("app/services/order_service.py", '''"""
Order business logic - Phase 5: Order Workflow.

This module is the ONLY place allowed to create/modify Order rows.
It enforces the order state machine, tenant isolation, inventory
validation, and transactional safety.

Architecture:
  Agent Tool -> OrderService -> Existing Services -> Database

The Agent must NEVER manipulate orders directly.
"""
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.inventory import Inventory
from app.services import product_service, inventory_service
from app.services.exceptions import (
    NotFoundError,
    OrderStateError,
    InsufficientInventoryError,
    OrderNotModifiableError,
)


# ============================================================
# STATE MACHINE
# ============================================================

# Valid transitions: current_status -> set of allowed next statuses
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.COMPLETED: set(),
}


def _validate_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Raise OrderStateError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise OrderStateError(
            f"Invalid transition: {current.value} -> {target.value}"
        )


# ============================================================
# TENANT-SAFE ORDER RETRIEVAL
# ============================================================

def _get_order_or_404(
    db: Session, store_id: uuid.UUID, order_id: uuid.UUID
) -> Order:
    """
    Fetch an order with strict tenant isolation.
    Returns 404-style error if order doesn't exist OR belongs to another store.
    """
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.store_id == store_id)
        .first()
    )
    if order is None:
        raise NotFoundError("Order not found")
    return order


def get_order(db: Session, store_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    """Public API: get a single order with tenant isolation."""
    return _get_order_or_404(db, store_id, order_id)


def list_orders(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
    limit: int = 50,
) -> list[Order]:
    """List orders for a store, optionally filtered by customer/status."""
    query = db.query(Order).filter(Order.store_id == store_id)
    if customer_id:
        query = query.filter(Order.customer_id == customer_id)
    if status:
        query = query.filter(Order.status == status)
    return query.order_by(Order.created_at.desc()).limit(limit).all()


# ============================================================
# DRAFT MANAGEMENT
# ============================================================

def create_draft(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> Order:
    """
    Create a new order draft. Does NOT touch inventory.
    The draft remains modifiable until confirmed.
    """
    order = Order(
        store_id=store_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        status=OrderStatus.DRAFT,
        total_amount=Decimal("0"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _ensure_draft(order: Order) -> None:
    """Raise if order is not in DRAFT state (cannot modify)."""
    if order.status != OrderStatus.DRAFT:
        raise OrderNotModifiableError(
            f"Order is in '{order.status.value}' state and cannot be modified"
        )


def add_item(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: int,
) -> OrderItem:
    """
    Add an item to a draft order.

    Business rules enforced:
    - Order must be in DRAFT state
    - Product must exist and belong to the same store
    - Product must be active
    - Quantity must be positive
    - Price is ALWAYS taken from the authoritative product record
      (the Agent/client can NEVER override the price)
    """
    order = _get_order_or_404(db, store_id, order_id)
    _ensure_draft(order)

    if quantity <= 0:
        raise ValueError("Quantity must be positive")

    # Get authoritative product (validates store ownership + existence)
    product = product_service.get_product(db, store_id, product_id)

    if not product.is_active:
        raise NotFoundError("Product is not available for sale")

    # Check if item already exists in this order -> update quantity
    existing_item = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order_id, OrderItem.product_id == product_id)
        .first()
    )

    if existing_item:
        existing_item.quantity += quantity
        item = existing_item
    else:
        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            product_name=product.name,
            quantity=quantity,
            unit_price=product.price,  # AUTHORITATIVE price from DB
        )
        db.add(item)

    # Recalculate order total
    _recalculate_total(db, order)
    db.commit()
    db.refresh(item)
    return item


def update_item(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: int,
) -> OrderItem:
    """Update the quantity of an item in a draft order."""
    order = _get_order_or_404(db, store_id, order_id)
    _ensure_draft(order)

    if quantity <= 0:
        raise ValueError("Quantity must be positive")

    item = (
        db.query(OrderItem)
        .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
        .first()
    )
    if item is None:
        raise NotFoundError("Order item not found")

    item.quantity = quantity
    _recalculate_total(db, order)
    db.commit()
    db.refresh(item)
    return item


def remove_item(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    """Remove an item from a draft order."""
    order = _get_order_or_404(db, store_id, order_id)
    _ensure_draft(order)

    item = (
        db.query(OrderItem)
        .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
        .first()
    )
    if item is None:
        raise NotFoundError("Order item not found")

    db.delete(item)
    _recalculate_total(db, order)
    db.commit()


def _recalculate_total(db: Session, order: Order) -> None:
    """Recalculate order total from its items. Called internally."""
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    total = sum(item.unit_price * item.quantity for item in items)
    order.total_amount = total


# ============================================================
# CONFIRMATION (Critical Transaction)
# ============================================================

def confirm_order(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
) -> Order:
    """
    Confirm a draft order. This is a CRITICAL transaction:

    1. Validate order is in DRAFT state
    2. Validate order has at least one item
    3. Validate sufficient inventory for ALL items
    4. Atomically: decrement inventory + set status to CONFIRMED

    Idempotency: if the order is already CONFIRMED, return it as-is
    (safe against duplicate requests from Agent retries).

    On ANY failure, the entire transaction is rolled back - no partial state.
    """
    order = _get_order_or_404(db, store_id, order_id)

    # Idempotency: already confirmed -> return as-is
    if order.status == OrderStatus.CONFIRMED:
        return order

    # Must be DRAFT to confirm
    if order.status != OrderStatus.DRAFT:
        raise OrderStateError(
            f"Cannot confirm order in '{order.status.value}' state"
        )

    # Must have items
    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    if not items:
        raise OrderStateError("Cannot confirm an empty order")

    # Validate inventory for ALL items BEFORE making any changes
    for item in items:
        inventory = inventory_service.get_inventory(db, store_id, item.product_id)
        if inventory.quantity < item.quantity:
            raise InsufficientInventoryError(
                f"Insufficient stock for '{item.product_name}': "
                f"requested {item.quantity}, available {inventory.quantity}"
            )

    # All checks passed -> perform atomic update
    try:
        for item in items:
            inventory = inventory_service.get_inventory(db, store_id, item.product_id)
            inventory.quantity -= item.quantity

        order.status = OrderStatus.CONFIRMED
        db.commit()
        db.refresh(order)
        return order

    except Exception:
        db.rollback()
        raise


# ============================================================
# CANCELLATION
# ============================================================

def cancel_order(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
) -> Order:
    """
    Cancel an order. Only allowed from DRAFT or CONFIRMED states.

    If the order was CONFIRMED (inventory already decremented),
    restore the inventory.
    """
    order = _get_order_or_404(db, store_id, order_id)

    # Idempotency: already cancelled
    if order.status == OrderStatus.CANCELLED:
        return order

    _validate_transition(order.status, OrderStatus.CANCELLED)

    # If confirmed, restore inventory
    if order.status == OrderStatus.CONFIRMED:
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            inventory = inventory_service.get_inventory(db, store_id, item.product_id)
            inventory.quantity += item.quantity

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)
    return order


# ============================================================
# STATUS TRANSITIONS (for post-confirmation lifecycle)
# ============================================================

def transition_status(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    target_status: OrderStatus,
) -> Order:
    """
    Transition an order to a new status following the state machine.
    Used for post-confirmation lifecycle (PROCESSING, SHIPPED, DELIVERED).
    """
    order = _get_order_or_404(db, store_id, order_id)
    _validate_transition(order.status, target_status)
    order.status = target_status
    db.commit()
    db.refresh(order)
    return order
''')

print("\n=== Part 2 Complete ===")
print("OrderService created with:")
print("  - State machine (DRAFT -> CONFIRMED -> PROCESSING -> SHIPPED -> DELIVERED)")
print("  - Tenant isolation on every operation")
print("  - Atomic confirmation with inventory validation")
print("  - Idempotent confirm/cancel")
print("  - Authoritative pricing (Agent cannot override)")
print("\nNext: Agent Tools + Tests")
