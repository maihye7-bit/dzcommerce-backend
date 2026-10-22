"""
Enhanced product search for Phase 8 Sales Agent.
Extends existing ProductService with multi-filter search capabilities.
"""

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.product import Product


def search_products(
    db: Session,
    store_id: uuid.UUID,
    query: str = "",
    category: Optional[str] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    limit: int = 5,
) -> list[Product]:
    """
    Search products with multiple filters.
    All queries are tenant-isolated by store_id.
    Only returns active products.
    """
    q = db.query(Product).filter(
        Product.store_id == store_id,
        Product.is_active == True,
    )

    # Text search (name, description, SKU)
    if query:
        search_term = f"%{query}%"
        q = q.filter(
            or_(
                Product.name.ilike(search_term),
                Product.description.ilike(search_term),
                Product.sku.ilike(search_term),
            )
        )

    # Category filter
    if category:
        q = q.filter(Product.category.ilike(f"%{category}%"))

    # Price range filters
    if min_price is not None:
        q = q.filter(Product.price >= min_price)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    return q.order_by(Product.created_at.desc()).limit(limit).all()
