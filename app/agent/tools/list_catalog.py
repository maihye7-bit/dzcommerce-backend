"""List a bounded set of active products from the current store catalog."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.conversation import Conversation
from app.models.product import Product


class ListCatalogProductsTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_catalog_products"

    @property
    def description(self) -> str:
        return "List up to five active products in the current store catalog."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        if context is None or context.get("db") is None:
            return ToolResult(
                success=False,
                error="Database context is required.",
                error_code="TOOL_ERROR",
            )

        db: Session = context["db"]
        products = (
            db.query(Product)
            .filter(
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .order_by(Product.name.asc(), Product.id.asc())
            .limit(5)
            .all()
        )
        result_products = [
            {
                "id": str(product.id),
                "name": product.name,
                "price": float(product.base_price),
            }
            for product in products
        ]

        if result_products and context.get("conversation_id"):
            conversation = (
                db.query(Conversation)
                .filter(
                    Conversation.id == context["conversation_id"],
                    Conversation.store_id == store_id,
                )
                .one_or_none()
            )
            if conversation is not None:
                metadata = dict(conversation.metadata_json or {})
                metadata.update(
                    commerce_stage="PRODUCT_CANDIDATES",
                    selected_product_id=None,
                    selected_product_name=None,
                    selected_variant_id=None,
                    selected_attributes={},
                    candidate_product_ids=[
                        product["id"] for product in result_products
                    ],
                    variant_index_map={},
                    variant_index_map_product_id=None,
                )
                conversation.metadata_json = metadata
                db.flush()

        return ToolResult(
            success=True,
            data={
                "products": result_products,
                "count": len(result_products),
                "catalog_listing": True,
            },
        )
