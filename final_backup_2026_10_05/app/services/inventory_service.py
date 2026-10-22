"""
Inventory business logic - Phase 12: Variant-based Stock Management.
"""
import uuid
from sqlalchemy.orm import Session
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.services.exceptions import NotFoundError, InsufficientInventoryError


def get_inventory_by_variant(
    db: Session,
    store_id: uuid.UUID,
    variant_id: uuid.UUID,
    for_update: bool = False,
) -> InventoryItem | None:
    query = db.query(InventoryItem).filter(
        InventoryItem.store_id == store_id,
        InventoryItem.variant_id == variant_id,
    )
    if for_update:
        # Row lock: prevents two concurrent confirmations from overselling.
        query = query.with_for_update()
    return query.first()


def get_available_quantity(db: Session, store_id: uuid.UUID, variant_id: uuid.UUID) -> int:
    variant = (
        db.query(ProductVariant)
        .join(Product, ProductVariant.product_id == Product.id)
        .filter(ProductVariant.id == variant_id, Product.store_id == store_id)
        .first()
    )
    if not variant:
        raise NotFoundError("Variant not found or does not belong to this store")

    inv_item = get_inventory_by_variant(db, store_id, variant_id)
    return inv_item.quantity if inv_item else 0


def deduct_stock(db: Session, store_id: uuid.UUID, variant_id: uuid.UUID, quantity: int) -> InventoryItem:
    if quantity <= 0:
        raise ValueError("Quantity to deduct must be positive")

    inv_item = get_inventory_by_variant(db, store_id, variant_id, for_update=True)
    if inv_item is None:
        raise InsufficientInventoryError(f"No inventory record for variant {variant_id}")
    if inv_item.quantity < quantity:
        raise InsufficientInventoryError(
            f"Insufficient stock. Available: {inv_item.quantity}, Requested: {quantity}"
        )

    inv_item.quantity -= quantity
    db.flush()
    return inv_item


def restore_stock(db: Session, store_id: uuid.UUID, variant_id: uuid.UUID, quantity: int) -> InventoryItem:
    if quantity <= 0:
        raise ValueError("Quantity to restore must be positive")

    inv_item = get_inventory_by_variant(db, store_id, variant_id, for_update=True)
    if inv_item is None:
        inv_item = InventoryItem(store_id=store_id, variant_id=variant_id, quantity=quantity)
        db.add(inv_item)
    else:
        inv_item.quantity += quantity

    db.flush()
    return inv_item
