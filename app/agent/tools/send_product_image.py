"""Send the selected product's registered primary image through Messenger."""

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.product import Product
from app.models.product_image import ProductImage
from app.services import product_image_storage
from app.services.exceptions import ImageStorageError
from app.services.messenger_media import (
    build_public_product_image_url,
    send_messenger_image,
)

logger = logging.getLogger(__name__)

_IMAGE_WORDS = re.compile(
    r"(?<!\w)(?:صور(?:ة|تين)?|تصويرة|تصاور|photo(?:s)?|image(?:s)?|picture(?:s)?)(?!\w)",
    re.IGNORECASE,
)
_IMAGE_REQUEST_WORDS = re.compile(
    r"(?<!\w)(?:ممكن|ابعث|ابعت|أرسل|ارسل|ابعثلي|ابعتلي|"
    r"أرسللي|ارسللي|وريني|ورّيني|اعطيني|أعطيني|هات|"
    r"نحب|حبيت|حاب|نقدر|نشوف|كاين|كاينة|عندك|عندكم|أريد|اريد|"
    r"send|show|give|can|could|see|avez|as|voir|envoyez|envoyer|montrez|montre)(?!\w)",
    re.IGNORECASE,
)


def is_product_image_request(message: str) -> bool:
    """Recognize explicit photo requests; this is not a general product intent."""
    normalized = (message or "").strip()
    if not _IMAGE_WORDS.search(normalized):
        return False
    return bool(
        _IMAGE_REQUEST_WORDS.search(normalized)
        or re.match(
            r"^\s*(?:صور(?:ة)?|photo(?:s)?|image(?:s)?)\b",
            normalized,
            re.IGNORECASE,
        )
    )


class SendProductImageTool(BaseTool):
    @property
    def name(self) -> str:
        return "send_product_image"

    @property
    def description(self) -> str:
        return (
            "Send the selected product's registered primary image to a Messenger "
            "customer after an explicit image request. The product and store are "
            "validated from conversation context."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The selected product ID supplied by the backend.",
                },
            },
            "required": ["product_id"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        context = context or {}
        if (
            context.get("channel") != "facebook"
            or not is_product_image_request(context.get("user_message", ""))
        ):
            return ToolResult(
                success=False,
                error="An explicit Messenger product-image request is required.",
                error_code="NOT_AUTHORIZED",
            )

        try:
            product_id = uuid.UUID(str(arguments.get("product_id")))
            conversation_id = uuid.UUID(str(context.get("conversation_id")))
            customer_id = uuid.UUID(str(context.get("customer_id")))
        except (ValueError, TypeError, AttributeError):
            return ToolResult(
                success=False,
                error="The selected product or conversation context is unavailable.",
                error_code="NOT_FOUND",
            )

        db: Session = context["db"]
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.store_id == store_id,
                Conversation.customer_id == customer_id,
                Conversation.channel == "facebook",
            )
            .one_or_none()
        )
        if conversation is None:
            return ToolResult(
                success=False,
                error="The selected product context is unavailable.",
                error_code="NOT_FOUND",
            )

        state = conversation.metadata_json or {}
        selected_product_id = state.get("selected_product_id")
        try:
            selected_product_uuid = uuid.UUID(str(selected_product_id))
        except (ValueError, TypeError, AttributeError):
            selected_product_uuid = None
        if selected_product_uuid is None or selected_product_uuid != product_id:
            return ToolResult(
                success=False,
                error="The product is not the selected product in this conversation.",
                error_code="NOT_FOUND",
            )

        product = (
            db.query(Product)
            .filter(
                Product.id == product_id,
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .one_or_none()
        )
        customer = (
            db.query(Customer)
            .filter(
                Customer.id == customer_id,
                Customer.store_id == store_id,
            )
            .one_or_none()
        )
        if product is None or customer is None or not customer.phone:
            return ToolResult(
                success=False,
                error="The selected product or Messenger recipient is unavailable.",
                error_code="NOT_FOUND",
            )

        image = (
            db.query(ProductImage)
            .filter(
                ProductImage.store_id == store_id,
                ProductImage.product_id == product.id,
            )
            .order_by(
                ProductImage.is_primary.desc(),
                ProductImage.display_order.asc(),
                ProductImage.created_at.asc(),
                ProductImage.id.asc(),
            )
            .first()
        )
        if image is None:
            return ToolResult(
                success=False,
                error="No registered image is available for this product.",
                error_code="NO_IMAGE",
            )

        try:
            product_image_storage.read_image(image.storage_key)
            public_url = build_public_product_image_url(image.image_url)
        except (ImageStorageError, ValueError) as exc:
            logger.warning(
                "messenger_product_image_unavailable store_id=%s failure_type=%s",
                str(store_id),
                type(exc).__name__,
            )
            return ToolResult(
                success=False,
                error="The product image is not publicly available right now.",
                error_code="IMAGE_UNAVAILABLE",
            )

        delivery = await send_messenger_image(str(customer.phone), public_url)
        if not delivery.delivered:
            logger.warning(
                "messenger_product_image_send_failed store_id=%s status_code=%s "
                "failure_code=%s",
                str(store_id),
                delivery.status_code or "unavailable",
                delivery.failure_code or "unknown",
            )
            return ToolResult(
                success=False,
                error="Messenger could not deliver the product image.",
                error_code="DELIVERY_FAILED",
            )

        logger.info(
            "messenger_product_image_sent store_id=%s status_code=%s",
            str(store_id),
            delivery.status_code or "unavailable",
        )
        return ToolResult(
            success=True,
            data={"delivered": True, "product_name": product.name},
        )
