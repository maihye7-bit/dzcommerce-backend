import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_store_membership
from app.database import get_db
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.models.store_user import StoreUser
from app.schemas.inventory import InventoryOut, InventoryUpdate
from app.services import inventory_service
from app.services.exceptions import NotFoundError

read_router = APIRouter(prefix="/api/stores/{store_id}/inventory", tags=["inventory"])
router = APIRouter(
    prefix="/api/stores/{store_id}/variants/{variant_id}/inventory", tags=["inventory"]
)


@read_router.get("/products")
def list_store_inventory(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Product, ProductVariant, InventoryItem)
        .outerjoin(ProductVariant, ProductVariant.product_id == Product.id)
        .outerjoin(
            InventoryItem,
            (InventoryItem.variant_id == ProductVariant.id)
            & (InventoryItem.store_id == store_id),
        )
        .filter(Product.store_id == membership.store_id, Product.is_active.is_(True))
        .order_by(Product.name, ProductVariant.name)
        .all()
    )

    products: dict[uuid.UUID, dict] = {}
    for product, variant, inventory in rows:
        product_data = products.setdefault(
            product.id,
            {
                "id": str(product.id),
                "name": product.name,
                "base_price": float(product.base_price),
                "variants": [],
            },
        )
        if variant is not None:
            product_data["variants"].append(
                {
                    "id": str(variant.id),
                    "name": variant.name,
                    "sku": variant.sku,
                    "quantity": inventory.quantity if inventory else 0,
                    "inventory_id": str(inventory.id) if inventory else None,
                }
            )
    return list(products.values())


@router.get("", response_model=InventoryOut)
def get_inventory(
    store_id: uuid.UUID,
    variant_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    try:
        return inventory_service.get_variant_stock(db, store_id, variant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("", response_model=InventoryOut)
def update_inventory(
    store_id: uuid.UUID,
    variant_id: uuid.UUID,
    payload: InventoryUpdate,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    try:
        return inventory_service.set_variant_stock(
            db, store_id, variant_id, payload.quantity
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
