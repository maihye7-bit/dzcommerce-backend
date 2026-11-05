"""Messenger image delivery and public product-image URL validation."""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings
from app.core.config import FACEBOOK_PAGE_ACCESS_TOKEN


@dataclass(frozen=True)
class MessengerDeliveryResult:
    delivered: bool
    status_code: int | None = None
    failure_code: str | None = None


def _configured_public_host() -> str:
    configured_domain = (settings.RAILWAY_PUBLIC_DOMAIN or "").strip().rstrip("/")
    if not configured_domain:
        raise ValueError("The Railway public domain is not configured.")
    parsed = urlsplit(
        configured_domain
        if "://" in configured_domain
        else f"https://{configured_domain}"
    )
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError("The configured public domain is invalid.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("The configured public domain is not public.")
    if parsed.hostname.casefold() in {"localhost", "localhost.localdomain"}:
        raise ValueError("The configured public domain is not public.")
    return parsed.hostname.casefold()


def build_public_product_image_url(image_url: str | None) -> str:
    """Build an HTTPS URL only for the public product-image content endpoint."""
    host = _configured_public_host()
    if not isinstance(image_url, str) or not image_url.strip():
        raise ValueError("The product image URL is missing.")

    image = urlsplit(image_url.strip())
    if image.scheme or image.netloc:
        if (
            image.scheme != "https"
            or image.hostname is None
            or image.hostname.casefold() != host
            or image.username
            or image.password
            or image.port not in (None, 443)
        ):
            raise ValueError("The product image URL is not on the configured public host.")
    elif not image.path.startswith("/") or image.path.startswith("//"):
        raise ValueError("The product image URL must be an absolute path.")

    parts = image.path.strip("/").split("/")
    if (
        len(parts) != 4
        or parts[:2] != ["api", "product-images"]
        or parts[3] != "content"
    ):
        raise ValueError("The product image URL is not a supported public endpoint.")
    try:
        import uuid

        uuid.UUID(parts[2])
    except (ValueError, AttributeError) as exc:
        raise ValueError("The product image URL has an invalid image identifier.") from exc
    if image.query or image.fragment:
        raise ValueError("The product image URL must not contain query or fragment data.")

    return urlunsplit(("https", host, image.path, "", ""))


async def send_messenger_image(
    recipient_id: str,
    image_url: str,
) -> MessengerDeliveryResult:
    """Send one image and require Meta's successful message ID response."""
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        return MessengerDeliveryResult(False, failure_code="missing_page_token")
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {"url": image_url},
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://graph.facebook.com/v26.0/me/messages",
                params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
                json=payload,
            )
    except httpx.HTTPError as exc:
        return MessengerDeliveryResult(
            False,
            failure_code=f"transport_{type(exc).__name__}",
        )

    if not response.is_success:
        return MessengerDeliveryResult(
            False,
            status_code=response.status_code,
            failure_code="graph_api_rejected",
        )
    try:
        message_id = response.json().get("message_id")
    except (ValueError, AttributeError):
        message_id = None
    if not isinstance(message_id, str) or not message_id:
        return MessengerDeliveryResult(
            False,
            status_code=response.status_code,
            failure_code="graph_response_missing_message_id",
        )
    return MessengerDeliveryResult(True, status_code=response.status_code)
