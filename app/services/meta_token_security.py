"""Encryption helpers for store-scoped Meta access tokens."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

TOKEN_PREFIX = "fernet:v1:"


class MetaTokenEncryptionError(ValueError):
    pass


def _fernet() -> Fernet:
    key = settings.SOCIAL_TOKEN_ENCRYPTION_KEY.strip()
    if not key:
        raise MetaTokenEncryptionError(
            "SOCIAL_TOKEN_ENCRYPTION_KEY is not configured"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise MetaTokenEncryptionError(
            "SOCIAL_TOKEN_ENCRYPTION_KEY is invalid"
        ) from exc


def encrypt_meta_token(access_token: str) -> str:
    if not access_token or not access_token.strip():
        raise MetaTokenEncryptionError("Meta access token is empty")
    encrypted = _fernet().encrypt(access_token.encode("utf-8")).decode("ascii")
    return f"{TOKEN_PREFIX}{encrypted}"


def decrypt_meta_token(stored_token: str) -> str:
    if not stored_token.startswith(TOKEN_PREFIX):
        raise MetaTokenEncryptionError("Stored Meta access token is not encrypted")
    try:
        return _fernet().decrypt(
            stored_token[len(TOKEN_PREFIX) :].encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise MetaTokenEncryptionError("Stored Meta access token is invalid") from exc
