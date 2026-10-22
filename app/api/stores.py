import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_current_user, get_store_membership
from app.database import get_db
from app.models.store import Store
from app.models.store_user import StoreUser
from app.models.user import User
from app.schemas.store import MyStoreOut, StoreOut, StoreUpdate

router = APIRouter(prefix="/api/stores", tags=["stores"])


@router.get("", response_model=list[MyStoreOut])
def list_my_stores(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lists only the stores the current user belongs to.
    This is the tenant-isolation guarantee at the list level: a user
    never sees stores they are not a member of.
    """
    memberships = db.query(StoreUser).filter(StoreUser.user_id == current_user.id).all()
    return [
        MyStoreOut(
            id=m.store.id,
            name=m.store.name,
            slug=m.store.slug,
            is_active=m.store.is_active,
            role=m.role,
        )
        for m in memberships
    ]


@router.get("/{store_id}", response_model=StoreOut)
def get_store(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
):
    """
    Returns a single store. `get_store_membership` already verified
    that the current user belongs to this store (404 otherwise), so by
    the time we get here access is guaranteed to be authorized.
    """
    return membership.store


@router.patch("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: uuid.UUID,
    payload: StoreUpdate,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data or update_data.get("name") is None:
        raise HTTPException(status_code=400, detail="No store fields supplied")
    store: Store = membership.store
    store.name = update_data["name"]
    db.commit()
    db.refresh(store)
    return store
