"""
Search Products Tool: Finds products by name or description.
PHASE 14 FINAL FIX: Persists data using 'selected_product_id' to match CommerceResolver contract.
"""
import uuid
from typing import Any
from sqlalchemy.orm import Session
from app.agent.tools.base import BaseTool, ToolResult
from app.models.product import Product
from app.models.conversation import Conversation


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
            db: Session = context["db"]
            query_term = args.get("query", "")

            # Perform Search with Tenant Isolation
            products = (
                db.query(Product)
                .filter(
                    Product.store_id == store_id,
                    Product.is_active == True,
                    Product.name.ilike(f"%{query_term}%")
                )
                .limit(5)
                .all()
            )

            if products:
                # PHASE 14 FINAL FIX: Persist using keys expected by CommerceResolver
                conv_id = context.get("conversation_id")
                if conv_id:
                    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
                    if conv:
                        if not conv.metadata_json:
                            conv.metadata_json = {}
                        
                        # Logic: If single result, auto-select. If multiple, keep candidates.
                        if len(products) == 1:
                            p = products[0]
                            # CRITICAL CHANGE: Use 'selected_product_id' directly
                            conv.metadata_json["selected_product_id"] = str(p.id)
                            conv.metadata_json["selected_product_name"] = p.name
                            conv.metadata_json.pop("candidate_product_ids", None)
                            
                            # Reset variant selection since product changed
                            conv.metadata_json.pop("selected_variant_id", None)
                            conv.metadata_json.pop("selected_attributes", None)
                            
                            # Explicitly set stage for clarity/debugging
                            conv.metadata_json["commerce_stage"] = "PRODUCT_SELECTED"
                        else:
                            # Multiple results: Don't auto-select yet
                            conv.metadata_json.pop("selected_product_id", None)
                            conv.metadata_json.pop("selected_product_name", None)
                            conv.metadata_json.pop("selected_variant_id", None)
                            conv.metadata_json.pop("selected_attributes", None)
                            conv.metadata_json["candidate_product_ids"] = [str(p.id) for p in products]
                            conv.metadata_json["commerce_stage"] = "PRODUCT_CANDIDATES"
                        
                        db.commit()

                product_list = [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "price": float(p.base_price),
                        "sku": p.sku,
                    }
                    for p in products
                ]

                return ToolResult(
                    success=True,
                    data={
                        "products": product_list,
                        "count": len(product_list),
                    },
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"No products found for '{query_term}'.",
                )

        except Exception as e:
            print(f"❌ SearchProductsTool Error: {e}")
            return ToolResult(success=False, error=f"Search failed: {str(e)}")
