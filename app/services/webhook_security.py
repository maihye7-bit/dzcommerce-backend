"""
WebhookSecurityService: Validates webhook signatures from Meta platforms.

Supports:
  - Facebook/Instagram: X-Hub-Signature-256 header (HMAC-SHA256)
  - WhatsApp Cloud API: X-Hub-Signature-256 header (HMAC-SHA256)

Both use the same HMAC-SHA256 mechanism with the app secret.
Reference: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
           https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
"""

import hashlib
import hmac
import os
from typing import Optional

from app.core.config import FACEBOOK_APP_SECRET


def _get_app_secret() -> str:
    """Get Meta app secret from environment. Never hard-code."""
    secret = os.environ.get("META_APP_SECRET") or FACEBOOK_APP_SECRET
    if not secret:
        raise RuntimeError(
            "META_APP_SECRET environment variable is not set. "
            "Webhook signature verification cannot proceed."
        )
    return secret


def verify_meta_signature(
    payload_body: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str] = None,
) -> bool:
    """
    Verify X-Hub-Signature-256 header from Meta webhooks.

    Used by Facebook Messenger, Facebook Comments, Instagram DMs,
    Instagram Comments, and WhatsApp Cloud API.

    Args:
        payload_body: Raw request body as bytes
        signature_header: Value of X-Hub-Signature-256 header
        app_secret: Override for testing; defaults to env var

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header:
        return False

    secret = app_secret or _get_app_secret()

    # Header format: sha256=<hex_digest>
    if not signature_header.startswith("sha256="):
        return False

    expected_hash = signature_header[7:]  # Strip "sha256=" prefix

    computed_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(computed_hash, expected_hash)


def verify_whatsapp_verify_token(
    verify_token_param: str,
) -> bool:
    """
    Verify the hub.verify_token parameter during WhatsApp webhook setup.

    During initial webhook registration, WhatsApp sends a GET request with
    hub.mode=subscribe, hub.verify_token=<token>, hub.challenge=<challenge>.
    We must validate the token and echo back the challenge.
    """
    expected_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if not expected_token:
        raise RuntimeError("WHATSAPP_VERIFY_TOKEN environment variable is not set.")
    return hmac.compare_digest(verify_token_param, expected_token)


def verify_meta_verify_token(
    verify_token_param: str,
) -> bool:
    """
    Verify the hub.verify_token parameter during Facebook/Instagram webhook setup.
    Same mechanism as WhatsApp but may use a different token value.
    """
    expected_token = os.environ.get("META_VERIFY_TOKEN") or os.environ.get(
        "FACEBOOK_VERIFY_TOKEN", ""
    )
    if not expected_token:
        raise RuntimeError("Meta webhook verification token is not configured.")
    return hmac.compare_digest(verify_token_param, expected_token)
