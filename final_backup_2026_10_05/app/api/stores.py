import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_store_membership
from app.database import get_db
from app.models.store_user import StoreUser
from app.models.user import User
from app.schemas.store import MyStoreOut, StoreOut

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
