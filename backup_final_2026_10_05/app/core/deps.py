"""
Shared FastAPI dependencies.
Authentication + Authorization via StoreUser membership.
Enforces strict tenant isolation.
"""
import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.security import decode_access_token
from app.database import get_db
from app.models.store_user import StoreUser
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate user via JWT token."""
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise CREDENTIALS_EXCEPTION
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise CREDENTIALS_EXCEPTION
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise CREDENTIALS_EXCEPTION
    return user


def get_store_membership(
    store_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StoreUser:
    """
    Verifies that current_user belongs to store_id.
    Raises 404 (not 403) to prevent information leakage about non-existent stores.
    Returns the StoreUser object containing role info for further authorization checks.
    """
    membership = (
        db.query(StoreUser)
        .filter(StoreUser.store_id == store_id, StoreUser.user_id == current_user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        )
    return membership
