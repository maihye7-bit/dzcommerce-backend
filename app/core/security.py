"""
Low-level security primitives: password hashing and JWT encode/decode.

No business logic here, and no direct DB access. Keeping this isolated
makes it easy to audit and to swap the hashing scheme or token format
later without touching the rest of the app.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# bcrypt_sha256 avoids bcrypt's 72-byte truncation; legacy bcrypt/Argon2 hashes remain verifiable.
pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt", "argon2"],
    deprecated=["argon2"],
)


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """
    Create a signed JWT whose `sub` claim is the user id (as a string).
    Kept intentionally minimal: no roles/store info inside the token,
    since store membership can change and must always be re-checked
    against the database (see app/core/deps.py).
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
