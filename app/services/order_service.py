"""
Order business logic - Phase 12: Order Workflow.
This module is the ONLY place allowed to create/modify Order rows.
It enforces the order state machine, tenant isolation, inventory
validation, and transactional safety.
"""
import uuid
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.services import inventory_service, product_service
from app.services.exceptions import (
    InsufficientInventoryError,
    NotFoundError,
    OrderNotModifiableError,
    OrderStateError,
)

# ============================================================
# STATE MACHINE
# ============================================================
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.WAITING_CONFIRMATION, OrderStatus.CANCELLED},
    OrderStatus.WAITING_CONFIRMATION: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.READY_TO_SHIP, OrderStatus.CANCELLED},
    OrderStatus.READY_TO_SHIP: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.HUMAN_HANDOFF: set(),
}


def _validate_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Raise OrderStateError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise OrderStateError(f"Invalid transition: {current.value} -> {target.value}")


# ============================================================
# TENANT-SAFE ORDER RETRIEVAL
# ============================================================
def _get_order_or_404(db: Session, store_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    """Fetch an order with strict tenant isolation."""
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
    """Create a new order draft. Does NOT touch inventory."""
    order = Order(
        store_id=store_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        status=OrderStatus.DRAFT,
        subtotal=Decimal("0"),
        shipping_cost=Decimal("0"),
        total=Decimal("0"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _ensure_modifiable(order: Order) -> None:
    """Raise if order is not in DRAFT or WAITING_CONFIRMATION state."""
    if order.status not in [OrderStatus.DRAFT, OrderStatus.WAITING_CONFIRMATION]:
        raise OrderNotModifiableError(
            f"Order is in '{order.status.value}' state and cannot be modified"
        )


def add_item(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None = None,
    quantity: int = 1,
    commit: bool = True,
) -> OrderItem:
    """Add an item to a draft order. Price is ALWAYS authoritative from DB."""
    order = _get_order_or_404(db, store_id, order_id)
    _ensure_modifiable(order)

    if quantity <= 0:
        raise ValueError("Quantity must be positive")

    product = product_service.get_product(db, store_id, product_id)
    if not product.is_active:
        raise NotFoundError("Product is not available for sale")

    unit_price = product.base_price
    if variant_id:
        variant = db.query(ProductVariant).filter(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
        ).first()
        if not variant:
            raise NotFoundError("Variant not found for this product")
        unit_price = product.base_price + variant.price_adjustment

    existing_item = (
        db.query(OrderItem)
        .filter(
            OrderItem.order_id == order_id,
            OrderItem.product_id == product_id,
            OrderItem.variant_id == variant_id,
        )
        .first()
    )

    if existing_item:
        existing_item.quantity += quantity
        item = existing_item
    else:
        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            variant_id=variant_id,
            quantity=quantity,
            unit_price=unit_price,
        )
        db.add(item)

    db.flush()
    _recalculate_totals(db, order)
    if commit:
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
    _ensure_modifiable(order)

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
    db.flush()
    _recalculate_totals(db, order)
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
    _ensure_modifiable(order)

    item = (
        db.query(OrderItem)
        .filter(OrderItem.id == item_id, OrderItem.order_id == order_id)
        .first()
    )
    if item is None:
        raise NotFoundError("Order item not found")

    db.delete(item)
    db.flush()
    _recalculate_totals(db, order)
    db.commit()


def _recalculate_totals(db: Session, order: Order) -> None:
    """Recalculate order subtotals and totals from its items."""
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    subtotal = sum((item.unit_price * item.quantity) for item in items)
    order.subtotal = subtotal
    order.total = subtotal + (order.shipping_cost or Decimal("0"))


# ============================================================
# CONFIRMATION (Critical Transaction)
# ============================================================
def confirm_order(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
) -> Order:
    """Confirm a draft/waiting order. Atomic transaction with inventory check."""
    order = _get_order_or_404(db, store_id, order_id)

    if order.status == OrderStatus.CONFIRMED:
        return order

    if order.status not in [OrderStatus.DRAFT, OrderStatus.WAITING_CONFIRMATION]:
        raise OrderStateError(
            f"Cannot confirm order in '{order.status.value}' state"
        )

    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    if not items:
        raise OrderStateError("Cannot confirm an empty order")

    # Check inventory availability first
    for item in items:
        if not item.variant_id:
            raise OrderStateError(
                f"Order item {item.id} has no variant_id. Cannot check inventory."
            )
        inv_qty = inventory_service.get_available_quantity(
            db, store_id, item.variant_id
        )
        if inv_qty < item.quantity:
            raise InsufficientInventoryError(
                f"Insufficient stock for variant {item.variant_id}: "
                f"requested {item.quantity}, available {inv_qty}"
            )

    try:
        for item in items:
            inventory_service.deduct_stock(
                db, store_id, item.variant_id, item.quantity
            )
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
    commit: bool = True,
) -> Order:
    """Cancel an order. Restores inventory if confirmed."""
    order = _get_order_or_404(db, store_id, order_id)

    if order.status == OrderStatus.CANCELLED:
        return order

    _validate_transition(order.status, OrderStatus.CANCELLED)

    if order.status == OrderStatus.CONFIRMED:
        items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
        for item in items:
            if item.variant_id:
                inventory_service.restore_stock(
                    db, store_id, item.variant_id, item.quantity
                )

    order.status = OrderStatus.CANCELLED
    if commit:
        db.commit()
        db.refresh(order)
    return order


# ============================================================
# STATUS TRANSITIONS
# ============================================================
def transition_status(
    db: Session,
    store_id: uuid.UUID,
    order_id: uuid.UUID,
    target_status: OrderStatus,
) -> Order:
    """Transition an order to a new status following the state machine."""
    order = _get_order_or_404(db, store_id, order_id)
    _validate_transition(order.status, target_status)
    order.status = target_status
    db.commit()
    db.refresh(order)
    return order
