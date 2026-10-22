"""
Search Products Tool: Finds products by name or description.
PHASE 14 FINAL FIX: Persists data using 'selected_product_id' to match CommerceResolver contract.
"""
import uuid
import logging
import re
import unicodedata
from typing import Any
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.agent.tools.base import BaseTool, ToolResult
from app.models.product import Product
from app.models.conversation import Conversation

logger = logging.getLogger(__name__)

_ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_ARABIC_LETTERS = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
    }
)
_SAMSUNG_VARIANTS = re.compile(r"(?<!\w)(?:samsung|سامسونغ|سامسونج)(?!\w)", re.IGNORECASE)


def normalize_product_search_text(value: str | None) -> str:
    """Normalize spelling conservatively for comparison without changing stored text."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = normalized.translate(_ARABIC_DIGITS).translate(_ARABIC_LETTERS)
    normalized = _SAMSUNG_VARIANTS.sub("سامسونغ", normalized)
    return re.sub(r"\s+", " ", normalized.casefold()).strip()


class SearchProductsTool(BaseTool):

    @property
    def name(self) -> str:
        return "search_products"

    @property
    def description(self) -> str:
        return (
            "Searches for products by name or description. "
            "Returns a list of matching products with their IDs. "
            "Use this first when the customer asks about availability."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The product name or keyword to search for.",
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            query_term = args.get("query")
            if not isinstance(query_term, str) or not query_term.strip():
                return ToolResult(
                    success=False,
                    error="Search query must be a non-empty string.",
                    error_code="INVALID_QUERY",
                )
            query_term = query_term.strip()
            normalized_query = normalize_product_search_text(query_term)
            db: Session = context["db"]

            # Fetch only this store's active products, then compare normalized
            # text in memory so spelling normalization is never persisted.
            store_products = (
                db.query(Product)
                .filter(
                    Product.store_id == store_id,
                    Product.is_active == True,
                )
                .all()
            )
            products = [
                product
                for product in store_products
                if normalized_query
                and (
                    normalized_query
                    in normalize_product_search_text(product.name)
                    or normalized_query
                    in normalize_product_search_text(product.description)
                )
            ][:5]

            if not products:
                return ToolResult(
                    success=False,
                    error=f"No products found for '{query_term}'.",
                    error_code="NO_RESULTS",
                )

            # A search may establish a new selection only when no draft is open;
            # an open draft and its selected item remain untouched.
            conv_id = context.get("conversation_id")
            if conv_id:
                conv = (
                    db.query(Conversation)
                    .filter(
                        Conversation.id == conv_id,
                        Conversation.store_id == store_id,
                    )
                    .first()
                )
                if conv:
                    active_draft = conv.active_draft_json or {}
                    has_active_draft = (
                        isinstance(active_draft, dict)
                        and isinstance(active_draft.get("items"), list)
                        and bool(active_draft["items"])
                    )
                    if not has_active_draft:
                        metadata = dict(conv.metadata_json or {})
                        metadata.update(
                            selected_product_id=None,
                            selected_product_name=None,
                            last_product_id=None,
                            last_product_name=None,
                            last_searched_product=None,
                            selected_variant_id=None,
                            selected_attributes={},
                            variant_index_map={},
                            variant_index_map_product_id=None,
                            candidate_product_ids=[],
                            commerce_stage="EMPTY",
                        )
                        if len(products) == 1:
                            product = products[0]
                            metadata.update(
                                selected_product_id=str(product.id),
                                selected_product_name=product.name,
                                last_product_id=str(product.id),
                                last_product_name=product.name,
                                last_searched_product={
                                    "id": str(product.id),
                                    "name": product.name,
                                },
                                commerce_stage="PRODUCT_SELECTED",
                            )
                        elif products:
                            metadata.update(
                                candidate_product_ids=[
                                    str(product.id) for product in products
                                ],
                                commerce_stage="PRODUCT_CANDIDATES",
                            )
                        conv.metadata_json = metadata
                        db.flush()

            product_list = [
                {
                    "id": str(product.id),
                    "name": product.name,
                    "price": float(product.base_price),
                    "sku": product.sku,
                }
                for product in products
            ]
            return ToolResult(
                success=True,
                data={"products": product_list, "count": len(product_list)},
            )

        except SQLAlchemyError as e:
            logger.exception("Database error while searching products")
            raise
        except Exception as e:
            logger.exception("Unexpected error while searching products")
            raise
