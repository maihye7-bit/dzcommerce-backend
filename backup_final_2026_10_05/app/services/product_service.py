"""
Product business logic - Phase 12: Variant-aware Creation & Search.
Handles creation of Products, their default Variants, associated Inventory, and Search.
"""
import uuid
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.product import Product, ProductVariant
from app.models.inventory import InventoryItem
from app.services.exceptions import NotFoundError, ValidationError


def get_product(db: Session, store_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    """Fetch a product with tenant isolation."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.store_id == store_id
    ).first()
    if not product:
        raise NotFoundError("Product not found")
    return product


def list_products(
    db: Session,
    store_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Product]:
    """List products for a store."""
    return (
        db.query(Product)
        .filter(Product.store_id == store_id, Product.is_active == True)
        .offset(offset)
        .limit(limit)
        .all()
    )


def search_products(
    db: Session,
    store_id: uuid.UUID,
    query: str,
    category: str | None = None,  # Kept for interface compat but unused in current model
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    limit: int = 5,
) -> list[Product]:
    """
    Search products by name or description with tenant isolation.
    Uses base_price for any potential future price filtering logic.
    """
    if not query or not query.strip():
        return []

    search_term = f"%{query.strip()}%"
    
    # Filter by Store ID (Critical for Multi-tenancy)
    # Only search active products
    q = db.query(Product).filter(
        Product.store_id == store_id,
        Product.is_active == True,
        # Search in Name OR Description
        (Product.name.ilike(search_term)) | (Product.description.ilike(search_term))
    )
    
    # Optional Price Filtering (if needed later)
    if min_price is not None:
        q = q.filter(Product.base_price >= min_price)
    if max_price is not None:
        q = q.filter(Product.base_price <= max_price)

    return q.limit(limit).all()


def create_product(
    db: Session,
    store_id: uuid.UUID,
    name: str,
    base_price: Decimal,
    description: str | None = None,
    sku: str | None = None,
    initial_quantity: int = 0,
) -> Product:
    """
    Create a new Product with a DEFAULT Variant and corresponding Inventory Item.
    Architecture Flow:
     1. Create Product
     2. Create Default Variant (linked to Product)
     3. Create Inventory Item (linked to Variant)
    """
    # 1. Validate Inputs
    if base_price < 0:
        raise ValidationError("Price cannot be negative")
    if initial_quantity < 0:
        raise ValidationError("Quantity cannot be negative")

    # 2. Create Product
    product = Product(
        store_id=store_id,
        name=name,
        description=description,
        base_price=base_price,
        sku=sku,
        is_active=True,
    )
    db.add(product)
    db.flush()  # Get product ID without committing yet

    # 3. Create Default Variant
    # Every product needs at least one variant to hold inventory in the new model
    default_variant = ProductVariant(
        product_id=product.id,
        name="Standard",  # Or use SKU if available
        price_adjustment=Decimal("0"),
    )
    db.add(default_variant)
    db.flush()  # Get variant ID

    # 4. Create Inventory Item linked to the Variant
    inventory_item = InventoryItem(
        store_id=store_id,
        variant_id=default_variant.id,
        quantity=initial_quantity,
        low_stock_threshold=5,
    )
    db.add(inventory_item)

    # Commit all together
    db.commit()
    db.refresh(product)
    # Load relationships for immediate access
    db.refresh(default_variant)
    db.refresh(inventory_item)
    
    # Attach to product object for convenience (optional but helpful)
    product.variants = [default_variant] 
    return product


def update_product(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    base_price: Decimal | None = None,
    is_active: bool | None = None,
) -> Product:
    """Update product details. Does NOT change inventory directly."""
    product = get_product(db, store_id, product_id)

    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if base_price is not None:
        if base_price < 0:
            raise ValidationError("Price cannot be negative")
        product.base_price = base_price
    if is_active is not None:
        product.is_active = is_active

    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, store_id: uuid.UUID, product_id: uuid.UUID) -> None:
    """Soft delete or hard delete depending on policy. Here we soft-delete by setting inactive."""
    product = get_product(db, store_id, product_id)
    product.is_active = False
    db.commit()
