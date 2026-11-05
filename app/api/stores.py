import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_current_user, get_store_membership
from app.database import get_db
from app.models.channel_account import ChannelAccount
from app.models.store import Store
from app.models.store_user import StoreUser
from app.models.user import User
from app.models.store_meta_token import StoreMetaToken
from app.schemas.store import MyStoreOut, StoreOut, StoreUpdate
from app.schemas.store_meta_connection import (
    StoreMetaConnection,
    StoreMetaConnectionRequest,
)
from app.services.meta_connection import MetaConnectionError, verify_facebook_page
from app.services.meta_token_security import (
    MetaTokenEncryptionError,
    decrypt_meta_token,
    encrypt_meta_token,
)

router = APIRouter(prefix="/stores", tags=["stores"])
logger = logging.getLogger(__name__)


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
    token = (
        db.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == store_id)
        .one_or_none()
    )
    if token is None:
        return StoreMetaConnection(
            status="incomplete",
            connected=False,
            verified=False,
        )
    account = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.store_id == store_id,
            ChannelAccount.channel == "facebook",
            ChannelAccount.external_account_id == token.page_id,
            ChannelAccount.is_active.is_(True),
        )
        .one_or_none()
    )
    if account is None:
        return StoreMetaConnection(
            status="incomplete",
            connected=False,
            verified=False,
        )
    try:
        decrypt_meta_token(token.access_token)
    except MetaTokenEncryptionError:
        return StoreMetaConnection(
            status="incomplete",
            connected=False,
            verified=False,
        )
    return StoreMetaConnection(
        status="connected",
        connected=True,
        verified=True,
        pageId=token.page_id,
        pageName=token.page_name,
    )


@router.post("/{store_id}/meta-connection", response_model=StoreMetaConnection)
async def connect_store_meta(
    store_id: uuid.UUID,
    payload: StoreMetaConnectionRequest,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    try:
        encrypted_access_token = encrypt_meta_token(payload.page_access_token)
    except MetaTokenEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secure Meta token storage is not configured.",
        ) from exc

    try:
        verified_page = await verify_facebook_page(
            page_id=payload.page_id,
            page_name=payload.page_name,
            page_access_token=payload.page_access_token,
        )
    except MetaConnectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    other_store_account = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.channel == "facebook",
            ChannelAccount.external_account_id == verified_page.page_id,
            ChannelAccount.store_id != store_id,
        )
        .first()
    )
    if other_store_account is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Facebook Page is already linked to another store.",
        )

    token = (
        db.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == store_id)
        .one_or_none()
    )
    if token is not None and token.instagram_page_id is not None:
        try:
            existing_access_token = decrypt_meta_token(token.access_token)
        except MetaTokenEncryptionError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The existing Instagram credential cannot be preserved while "
                    "connecting Facebook."
                ),
            ) from exc
        if existing_access_token != payload.page_access_token:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This store uses a different Instagram credential. "
                    "Connecting Facebook would replace it."
                ),
            )

    try:
        accounts = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.store_id == store_id,
                ChannelAccount.channel == "facebook",
            )
            .all()
        )
        account = next(
            (
                item
                for item in accounts
                if item.external_account_id == verified_page.page_id
            ),
            None,
        )
        for existing_account in accounts:
            existing_account.is_active = existing_account is account
        if account is None:
            account = ChannelAccount(
                store_id=store_id,
                channel="facebook",
                external_account_id=verified_page.page_id,
                external_account_name=verified_page.page_name,
                is_active=True,
            )
            db.add(account)
        else:
            account.external_account_name = verified_page.page_name
            account.is_active = True

        if token is None:
            token = StoreMetaToken(
                store_id=store_id,
                page_id=verified_page.page_id,
                page_name=verified_page.page_name,
                access_token=encrypted_access_token,
            )
            db.add(token)
        else:
            token.page_id = verified_page.page_id
            token.page_name = verified_page.page_name
            token.access_token = encrypted_access_token
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "facebook_page_link_conflict store_id=%s",
            str(store_id),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Facebook Page connection conflicts with an existing link.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.error(
            "facebook_page_link_save_failed store_id=%s error_type=%s",
            str(store_id),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The Facebook Page connection could not be saved.",
        ) from exc

    return StoreMetaConnection(
        status="connected",
        connected=True,
        verified=True,
        pageId=verified_page.page_id,
        pageName=verified_page.page_name,
    )


@router.delete("/{store_id}/meta-connection", response_model=StoreMetaConnection)
def disconnect_store_meta(
    store_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    token = db.query(StoreMetaToken).filter(StoreMetaToken.store_id == store_id).first()
    if token:
        try:
            (
                db.query(ChannelAccount)
                .filter(
                    ChannelAccount.store_id == store_id,
                    ChannelAccount.channel == "facebook",
                    ChannelAccount.external_account_id == token.page_id,
                    ChannelAccount.is_active.is_(True),
                )
                .update({ChannelAccount.is_active: False})
            )
            if token.instagram_page_id is None:
                db.delete(token)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception(
                "facebook_page_disconnect_failed store_id=%s error_type=%s",
                str(store_id),
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The Facebook Page connection could not be removed.",
            ) from exc
    return StoreMetaConnection(
        status="incomplete",
        connected=False,
        verified=False,
    )
