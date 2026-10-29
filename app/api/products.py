import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_store_membership
from app.database import get_db
from app.models.store_user import StoreUser
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services import product_service
from app.services.exceptions import DuplicateSKUError, NotFoundError

# store_id is part of every path here so that `get_store_membership`
# (which reads a `store_id` path parameter) applies to all of them --
# no route in this router can be reached without proving membership in
# that exact store first.
router = APIRouter(prefix="/stores/{store_id}/products", tags=["products"])


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    store_id: uuid.UUID,
    payload: ProductCreate,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    try:
        return product_service.create_product(
            db,
            store_id,
            name=payload.name,
            description=payload.description,
            sku=payload.sku,
            base_price=payload.price,
            initial_quantity=payload.initial_quantity,
        )
    except DuplicateSKUError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[ProductOut])
def list_products(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    return product_service.list_products(db, store_id)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    try:
        return product_service.get_product(db, store_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductUpdate,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    update_data = payload.model_dump(exclude_unset=True)
    try:
        return product_service.update_product(
            db,
            store_id,
            product_id,
            name=update_data.get("name"),
            description=update_data.get("description"),
            base_price=update_data.get("price"),
            sku=update_data.get("sku"),
            update_sku="sku" in update_data,
            is_active=update_data.get("is_active"),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DuplicateSKUError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Soft-deletes (deactivates) the product."""
    try:
        product_service.delete_product(db, store_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return None
