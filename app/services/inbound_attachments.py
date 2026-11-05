"""Download and persist supported Messenger image attachments."""

import uuid

import httpx

from app.services import product_image_service, product_image_storage
from app.services.exceptions import ImageStorageError, InvalidImageError

MAX_ATTACHMENT_SIZE = product_image_service.MAX_FILE_SIZE
_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class InboundAttachmentError(ValueError):
    """A safe, non-sensitive failure while receiving an external attachment."""

    def __init__(self, failure_code: str):
        super().__init__(failure_code)
        self.failure_code = failure_code


def _is_meta_media_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.casefold().rstrip(".")
    return (
        normalized == "facebook.com"
        or normalized.endswith(".facebook.com")
        or normalized == "fbcdn.net"
        or normalized.endswith(".fbcdn.net")
        or normalized == "fbsbx.com"
        or normalized.endswith(".fbsbx.com")
    )


async def download_and_store_meta_image(url: str) -> dict[str, object]:
    """Fetch a Meta-hosted image, validate its bytes, then store it on the image volume."""
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise InboundAttachmentError("invalid_attachment_url") from exc
    if (
        parsed.scheme != "https"
        or not _is_meta_media_host(parsed.hostname)
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise InboundAttachmentError("invalid_attachment_url")

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise InboundAttachmentError("attachment_unavailable")
                mime_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if mime_type not in _MIME_EXTENSIONS:
                    raise InboundAttachmentError("unsupported_attachment_type")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_ATTACHMENT_SIZE:
                    raise InboundAttachmentError("attachment_too_large")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_ATTACHMENT_SIZE:
                        raise InboundAttachmentError("attachment_too_large")
    except InboundAttachmentError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise InboundAttachmentError("attachment_download_failed") from exc

    try:
        validated = product_image_service.process_image_file(bytes(content), mime_type)
        storage_key = (
            f"conversation-attachments/{uuid.uuid4().hex}{validated.extension}"
        )
        product_image_storage.save_image(storage_key, validated.content)
    except InvalidImageError as exc:
        raise InboundAttachmentError("invalid_image_content") from exc
    except ImageStorageError as exc:
        raise InboundAttachmentError("attachment_storage_unavailable") from exc

    return {
        "type": "image",
        "status": "stored",
        "storage_key": storage_key,
        "mime_type": validated.mime_type,
        "file_size": len(validated.content),
        "width": validated.width,
        "height": validated.height,
    }
