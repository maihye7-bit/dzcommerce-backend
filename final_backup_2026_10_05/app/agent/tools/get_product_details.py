"""
Get Product Details Tool: Returns variants with SHORT INDICES.
Stores index -> real variant_id mapping in Conversation.metadata_json.
Does not expose UUIDs to the LLM for ordering.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.conversation import Conversation
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant


def _safe_uuid(value: Any) -> uuid.UUID | None:
    """
    Safely parse a UUID-like value.
    Returns None if invalid.
    """
    if value is None:
        return None

    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


class GetProductDetailsTool(BaseTool):

    @property
    def name(self) -> str:
        return "get_product_details"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a specific product. "
            "Returns available variants with short numeric indexes: 1, 2, 3... "
            "Use these indexes with create_order_draft. "
            "Do not use raw UUIDs when creating a draft."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": (
                        "The exact product UUID returned by search_products. "
                        "If omitted or invalid, the backend may use the currently selected product context."
                    ),
                },
            },
            "required": [],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            db: Session = context["db"]
            conversation_id = context.get("conversation_id")

            # 1. Try to parse product_id safely
            product_id = _safe_uuid(args.get("product_id"))

            # 2. If invalid/missing, fallback to selected product from conversation metadata
            conv = None
            if conversation_id:
                conv = db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()

            if product_id is None and conv is not None and conv.metadata_json:
                selected_product = conv.metadata_json.get("last_searched_product") or {}
                product_id = _safe_uuid(selected_product.get("id"))

            if product_id is None:
                return ToolResult(
                    success=False,
                    error=(
                        "Invalid or missing product_id. "
                        "Use the exact product id returned by search_products, "
                        "or ask the customer to choose a product first."
                    ),
                )

            # 3. Fetch product with tenant isolation
            product = db.query(Product).filter(
                Product.id == product_id,
                Product.store_id == store_id,
                Product.is_active == True,
            ).first()

            if not product:
                return ToolResult(
                    success=False,
                    error="Product not found, inactive, or does not belong to this store.",
                )

            # 4. Fetch variants with stock
            variants_rows = (
                db.query(ProductVariant, InventoryItem.quantity.label("stock"))
                .outerjoin(InventoryItem, ProductVariant.id == InventoryItem.variant_id)
                .filter(ProductVariant.product_id == product.id)
                .order_by(ProductVariant.created_at.asc())
                .all()
            )

            if not variants_rows:
                return ToolResult(
                    success=False,
                    error="This product has no variants available.",
                )

            variants_data = []
            variant_map: dict[str, str] = {}

            for idx, (variant, stock) in enumerate(variants_rows, start=1):
                adjustment = getattr(variant, "price_adjustment", 0) or 0
                final_price = float(product.base_price) + float(adjustment)

                attributes = getattr(variant, "attributes_json", {}) or {}

                # Store mapping using string keys for JSON compatibility
                variant_map[str(idx)] = str(variant.id)

                variants_data.append(
                    {
                        "index": idx,
                        "name": variant.name,
                        "attributes": attributes,
                        "final_price": final_price,
                        "stock_available": int(stock) if stock is not None else 0,
                    }
                )

            # 5. Persist mapping into conversation metadata
            if conv is not None:
                if not conv.metadata_json:
                    conv.metadata_json = {}

                conv.metadata_json["variant_index_map"] = variant_map
                conv.metadata_json["last_product_id"] = str(product.id)
                conv.metadata_json["last_product_name"] = product.name

                # Optional cleanup: remove obsolete selected variant if present
                conv.metadata_json.pop("selected_variant_id", None)

                db.flush()

            return ToolResult(
                success=True,
                data={
                    "product": {
                        "id": str(product.id),
                        "name": product.name,
                        "base_price": float(product.base_price),
                    },
                    "variants": variants_data,
                    "instruction": (
                        "To create a draft, call create_order_draft using variant_index, "
                        "not variant_id. Example: variant_index=1."
                    ),
                },
            )

        except Exception as e:
            print(f"❌ GetProductDetails Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return ToolResult(
                success=False,
                error=f"Failed to get product details: {str(e)}",
            )
