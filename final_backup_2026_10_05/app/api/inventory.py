import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_store_membership
from app.database import get_db
from app.models.store_user import StoreUser
from app.schemas.inventory import InventoryOut, InventoryUpdate
from app.services import inventory_service
from app.services.exceptions import NotFoundError

router = APIRouter(
    prefix="/api/stores/{store_id}/products/{product_id}/inventory", tags=["inventory"]
)


@router.get("", response_model=InventoryOut)
def get_inventory(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    try:
        return inventory_service.get_inventory(db, store_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("", response_model=InventoryOut)
def update_inventory(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: InventoryUpdate,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    try:
        return inventory_service.set_inventory_quantity(
            db, store_id, product_id, payload.quantity
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
