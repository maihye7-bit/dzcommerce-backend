import re
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import (create_access_token, hash_password,
                               verify_password)
from app.database import get_db
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_RATE_LIMIT_ATTEMPTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_lock = threading.Lock()
_rate_limit_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _enforce_rate_limit(action: str, identifier: str) -> None:
    """Allow at most five auth attempts per normalized identifier per minute."""
    now = time.monotonic()
    key = (action, identifier.strip().casefold())
    with _rate_limit_lock:
        attempts = _rate_limit_buckets[key]
        while attempts and now - attempts[0] >= _RATE_LIMIT_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= _RATE_LIMIT_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
            )
        attempts.append(now)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "store"


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    _enforce_rate_limit("register", payload.email)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    base_slug = _slugify(payload.store_name)
    slug = base_slug
    suffix = 1
    while db.query(Store).filter(Store.slug == slug).first() is not None:
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.flush()

    store = Store(name=payload.store_name, slug=slug)
    db.add(store)
    db.flush()

    membership = StoreUser(store_id=store.id, user_id=user.id, role=StoreRole.OWNER)
    db.add(membership)
    db.commit()

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.post(
    "/login", response_model=TokenResponse
)  # Fixed: Removed space in "/login "
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    """
    OAuth2-password-flow compatible login.
    """
    _enforce_rate_limit("login", form_data.username)
    user = db.query(User).filter(User.email == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,  # Fixed: Corrected typo 'stat us_code'
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user
