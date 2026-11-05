"""
Get Product Details Tool: Returns variants with SHORT INDICES.
Stores index -> real variant_id mapping in Conversation.metadata_json.
Does not expose UUIDs to the LLM for ordering.
"""
import uuid
import logging
from typing import Any
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.conversation import Conversation
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.models.product_image import ProductImage

logger = logging.getLogger(__name__)


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
            "Returns its stored description, registered images, variants, attributes, "
            "database prices, and inventory. Use this for product questions about "
            "features, sizes, colors, or photos. Variants have short numeric indexes "
            "for create_order_draft. "
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
                "product_name": {
                    "type": "string",
                    "description": "Optional product name from the current search results.",
                },
            },
            "additionalProperties": False,
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
                    Conversation.id == conversation_id,
                    Conversation.store_id == store_id,
                ).first()

            if product_id is None and conv is not None and conv.metadata_json:
                selected_product = conv.metadata_json.get("last_searched_product") or {}
                product_id = _safe_uuid(selected_product.get("id"))
            if product_id is None and isinstance(args.get("product_name"), str):
                matches = (
                    db.query(Product)
                    .filter(
                        Product.store_id == store_id,
                        Product.is_active.is_(True),
                        Product.name == args["product_name"].strip(),
                    )
                    .limit(2)
                    .all()
                )
                if len(matches) == 1:
                    product_id = matches[0].id

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
                .outerjoin(
                    InventoryItem,
                    (ProductVariant.id == InventoryItem.variant_id)
                    & (InventoryItem.store_id == store_id),
                )
                .filter(ProductVariant.product_id == product.id)
                .order_by(ProductVariant.created_at.asc(), ProductVariant.id.asc())
                .all()
            )

            variants_data = []
            variant_map: dict[str, str] = {}
            available_variants = []

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
                        "stock_available": int(stock) if stock is not None else None,
                        "stock_status": (
                            "available"
                            if stock is not None and stock > 0
                            else "out_of_stock"
                            if stock is not None
                            else "unknown"
                        ),
                    }
                )
                if stock is not None and stock > 0:
                    available_variants.append(
                        {
                            "id": str(variant.id),
                            "index": idx,
                            "name": variant.name,
                            "attributes": attributes,
                            "final_price": final_price,
                            "stock_available": int(stock),
                        }
                    )

            image_schema_available = inspect(db.get_bind()).has_table(
                    ProductImage.__tablename__
            )
            images_data = []
            if image_schema_available:
                    images_data = [
                        {
                            "url": image.image_url,
                            "thumbnail_url": image.thumbnail_url,
                            "is_primary": image.is_primary,
                            "width": image.width,
                            "height": image.height,
                        }
                        for image in (
                            db.query(ProductImage)
                            .filter(
                                ProductImage.store_id == store_id,
                                ProductImage.product_id == product.id,
                            )
                            .order_by(
                                ProductImage.display_order.asc(),
                                ProductImage.created_at.asc(),
                                ProductImage.id.asc(),
                            )
                            .limit(20)
                            .all()
                        )
                    ]
            else:
                    logger.warning(
                        "Product image details unavailable because table is missing"
                    )

            auto_selected_variant = (
                    available_variants[0] if len(available_variants) == 1 else None
            )
            # 5. Persist mapping into conversation metadata
            if conv is not None:
                    metadata = dict(conv.metadata_json or {})
                    has_active_draft = bool(
                        isinstance(conv.active_draft_json, dict)
                        and conv.active_draft_json.get("items")
                    )
                    metadata.update(
                        variant_index_map=variant_map,
                        variant_index_map_product_id=str(product.id),
                        last_product_id=str(product.id),
                        last_product_name=product.name,
                    )
                    if not has_active_draft:
                        metadata.update(
                            selected_product_id=str(product.id),
                            selected_product_name=product.name,
                            candidate_product_ids=[],
                        )
                        selected_variant_id = _safe_uuid(
                            metadata.get("selected_variant_id")
                        )
                        selected_variant = next(
                            (
                                variant
                                for variant, _stock in variants_rows
                                if variant.id == selected_variant_id
                            ),
                            None,
                        )
                        if selected_variant is not None:
                            metadata.update(
                                selected_variant_id=str(selected_variant.id),
                                selected_attributes=(
                                    selected_variant.attributes_json
                                    if isinstance(
                                        selected_variant.attributes_json, dict
                                    )
                                    else {}
                                ),
                                commerce_stage="VARIANT_SELECTED",
                            )
                        elif auto_selected_variant is not None:
                            metadata.update(
                                selected_variant_id=auto_selected_variant["id"],
                                selected_attributes=(
                                    auto_selected_variant["attributes"]
                                    if isinstance(
                                        auto_selected_variant["attributes"], dict
                                    )
                                    else {}
                                ),
                                commerce_stage="VARIANT_SELECTED",
                            )
                        else:
                            metadata.update(
                                selected_variant_id=None,
                                selected_attributes={},
                                commerce_stage="PRODUCT_SELECTED",
                            )
                    if auto_selected_variant is not None:
                        if not has_active_draft:
                            metadata.update(
                                selected_product_id=str(product.id),
                                selected_product_name=product.name,
                                selected_variant_id=auto_selected_variant["id"],
                                selected_attributes=(
                                    auto_selected_variant["attributes"]
                                    if isinstance(auto_selected_variant["attributes"], dict)
                                    else {}
                                ),
                                commerce_stage="VARIANT_SELECTED",
                            )
                    conv.metadata_json = metadata
                    db.flush()

            result_data = {
                    "product": {
                        "id": str(product.id),
                        "name": product.name,
                        "description": product.description,
                        "base_price": float(product.base_price),
                    },
                    "variants": variants_data,
                    "images": images_data,
                    "images_status": (
                        "available"
                        if images_data
                        else "none"
                        if image_schema_available
                        else "schema_unavailable"
                    ),
                    "variant_id_map": variant_map,
                "instruction": (
                    "To create a draft, call create_order_draft using variant_index, "
                    "not variant_id. Example: variant_index=1."
                ),
            }
            if auto_selected_variant is not None:
                result_data["auto_selected_variant"] = auto_selected_variant

            return ToolResult(
                success=True,
                data=result_data,
            )

        except SQLAlchemyError:
            raise
        except Exception as e:
            print(f"❌ GetProductDetails Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return ToolResult(
                success=False,
                error=f"Failed to get product details: {str(e)}",
            )
