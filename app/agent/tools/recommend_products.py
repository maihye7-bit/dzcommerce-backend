"""
recommend_products tool: Deterministic product recommendations.
Finds alternatives based on category, price range, or attributes.
NO AI/ML ranking - pure database queries for reliability.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import product_service


class RecommendProductsTool(BaseTool):
    @property
    def name(self) -> str:
        return "recommend_products"

    @property
    def description(self) -> str:
        return (
            "Find alternative or recommended products based on category, "
            "price range, or product attributes. Use this when: "
            "- The requested product is out of stock "
            "- Customer asks for 'something similar' or 'cheaper option' "
            "- You want to suggest complementary items. "
            "Results are deterministic and based on actual store data."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "based_on_product_id": {
                    "type": "string",
                    "description": "UUID of the reference product (optional)",
                },
                "category": {
                    "type": "string",
                    "description": "Category to search within",
                },
                "max_price": {
                    "type": "number",
                    "description": "Maximum price for recommendations",
                },
                "reason": {
                    "type": "string",
                    "enum": [
                        "out_of_stock_alternative",
                        "cheaper_option",
                        "complementary",
                        "general",
                    ],
                    "description": "Why are we recommending?",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max recommendations (default 3, max 10)",
                },
            },
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

            based_on_id = args.get("based_on_product_id")
            category = args.get("category")
            max_price = (
                Decimal(str(args["max_price"])) if args.get("max_price") else None
            )
            reason = args.get("reason", "general")
            limit = min(int(args.get("limit", 3)), 10)

            # If based on a specific product, get its attributes first
            ref_product = None
            if based_on_id:
                try:
                    ref_product = product_service.get_product(
                        db, store_id, uuid.UUID(based_on_id)
                    )
                    if not category:
                        category = ref_product.category
                    if not max_price and reason == "cheaper_option":
                        max_price = ref_product.price
                except Exception:
                    pass  # Proceed without reference product

            # Search for alternatives using existing service
            products = product_service.search_products(
                db=db,
                store_id=store_id,
                query="",
                category=category,
                max_price=max_price,
                limit=limit + 1,  # Get one extra to exclude reference
            )

            # Exclude the reference product itself
            recommendations = [
                p
                for p in products
                if not ref_product or str(p.id) != str(ref_product.id)
            ][:limit]

            return ToolResult(
                success=True,
                data={
                    "recommendations": [
                        {
                            "id": str(p.id),
                            "name": p.name,
                            "price": str(p.price),
                            "currency": "DZD",
                            "category": p.category,
                            "reason": reason,
                        }
                        for p in recommendations
                    ],
                    "count": len(recommendations),
                    "based_on": str(ref_product.id) if ref_product else None,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Recommendation failed: {str(e)}")
