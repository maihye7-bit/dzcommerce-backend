import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_current_user, get_store_membership
from app.database import get_db
from app.models.store import Store
from app.models.store_user import StoreUser
from app.models.user import User
from app.models.meta_app_config import MetaAppConfig
from app.models.store_meta_token import StoreMetaToken
from app.schemas.store import MyStoreOut, StoreOut, StoreUpdate
from app.schemas.store_meta_connection import StoreMetaConnection

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


@router.get("/{store_id}/meta-connection", response_model=StoreMetaConnection)
def get_store_meta_connection(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    token = db.query(StoreMetaToken).filter(StoreMetaToken.store_id == store_id).first()
    if not token:
        return StoreMetaConnection(connected=False, pageId=None, pageName=None)
    return StoreMetaConnection(connected=True, pageId=token.page_id, pageName=token.page_name)


@router.post("/{store_id}/meta-connection", response_model=StoreMetaConnection)
def connect_store_meta(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    # In a real implementation, this would initiate the OAuth flow.
    # For simplicity, we'll create a mock connection.
    # We'll check if there's already a token and update it, otherwise create.
    token = db.query(StoreMetaToken).filter(StoreMetaToken.store_id == store_id).first()
    if not token:
        token = StoreMetaToken(
            store_id=store_id,
            page_id="1234567890",  # Mock page ID
            page_name="Mock Page Name",
            access_token="mock_access_token",  # In production, this would be the real token from OAuth
        )
        db.add(token)
    else:
        token.page_id = "1234567890"
        token.page_name = "Mock Page Name"
        token.access_token = "mock_access_token"
    db.commit()
    db.refresh(token)
    return StoreMetaConnection(connected=True, pageId=token.page_id, pageName=token.page_name)


@router.delete("/{store_id}/meta-connection", response_model=StoreMetaConnection)
def disconnect_store_meta(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    token = db.query(StoreMetaToken).filter(StoreMetaToken.store_id == store_id).first()
    if token:
        db.delete(token)
        db.commit()
    return StoreMetaConnection(connected=False, pageId=None, pageName=None)
