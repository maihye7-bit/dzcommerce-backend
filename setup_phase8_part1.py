"""
Phase 8 Part 1 - Product Discovery Tools
Run: python setup_phase8_part1.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 8 Part 1: Product Discovery Tools ===\n")

# ============================================================
# 1. ENHANCED SEARCH PRODUCTS TOOL
# ============================================================
write_file("app/agent/tools/search_products.py", '''"""
search_products tool: Enhanced for Phase 8 Sales Agent.
Supports name, category, and price range filtering.
All data is authoritative from ProductService.
"""
import uuid
from typing import Any
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import product_service


class SearchProductsTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_products"

    @property
    def description(self) -> str:
        return (
            "Search for products by name, category, or price range. "
            "Use this when a customer asks about available products, prices, "
            "or specific items. Supports Arabic, Darija, and French queries. "
            "Returns only active products belonging to the current store."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (product name, category, or description)",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category name",
                },
                "min_price": {
                    "type": "number",
                    "description": "Minimum price filter",
                },
                "max_price": {
                    "type": "number",
                    "description": "Maximum price filter",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5, max 20)",
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

            query = args.get("query", "")
            category = args.get("category")
            min_price = Decimal(str(args["min_price"])) if args.get("min_price") else None
            max_price = Decimal(str(args["max_price"])) if args.get("max_price") else None
            limit = min(int(args.get("limit", 5)), 20)

            # Use existing product service with enhanced filtering
            products = product_service.search_products(
                db=db,
                store_id=store_id,
                query=query,
                category=category,
                min_price=min_price,
                max_price=max_price,
                limit=limit,
            )

            if not products:
                return ToolResult(
                    success=True,
                    data={
                        "products": [],
                        "count": 0,
                        "message": "No products found matching your criteria.",
                    },
                )

            return ToolResult(
                success=True,
                data={
                    "products": [
                        {
                            "id": str(p.id),
                            "name": p.name,
                            "price": str(p.price),
                            "currency": "DZD",
                            "category": p.category,
                            "description": p.description[:200] if p.description else None,
                            "is_active": p.is_active,
                        }
                        for p in products
                    ],
                    "count": len(products),
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {str(e)}")
''')

# ============================================================
# 2. GET PRODUCT DETAILS TOOL
# ============================================================
write_file("app/agent/tools/get_product_details.py", '''"""
get_product_details tool: Returns authoritative product information.
Includes stock, variants, SKU, and full description.
Price and inventory are NEVER invented by the LLM.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import product_service, inventory_service
from app.services.exceptions import NotFoundError


class GetProductDetailsTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_product_details"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a specific product including "
            "current stock quantity, price, SKU, description, and availability. "
            "Use this when a customer asks 'how much?', 'is it available?', "
            "'what colors/sizes?', or 'do you have X in stock?'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "UUID of the product to look up",
                },
            },
            "required": ["product_id"],
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
            product_id = uuid.UUID(args["product_id"])

            # Get authoritative product data
            product = product_service.get_product(db, store_id, product_id)

            # Get authoritative inventory data
            try:
                inventory = inventory_service.get_inventory(db, store_id, product_id)
                stock_qty = inventory.quantity
            except NotFoundError:
                stock_qty = 0

            return ToolResult(
                success=True,
                data={
                    "id": str(product.id),
                    "name": product.name,
                    "sku": product.sku,
                    "price": str(product.price),
                    "currency": "DZD",
                    "category": product.category,
                    "description": product.description,
                    "is_active": product.is_active,
                    "stock_quantity": stock_qty,
                    "in_stock": stock_qty > 0,
                    "variants": product.variants if hasattr(product, "variants") else [],
                },
            )

        except NotFoundError:
            return ToolResult(success=False, error="Product not found")
        except (ValueError, KeyError) as e:
            return ToolResult(success=False, error="Invalid product_id format")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to get product details: {str(e)}")
''')

# ============================================================
# 3. RECOMMEND PRODUCTS TOOL
# ============================================================
write_file("app/agent/tools/recommend_products.py", '''"""
recommend_products tool: Deterministic product recommendations.
Finds alternatives based on category, price range, or attributes.
NO AI/ML ranking - pure database queries for reliability.
"""
import uuid
from typing import Any
from decimal import Decimal

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
                    "enum": ["out_of_stock_alternative", "cheaper_option", "complementary", "general"],
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
            max_price = Decimal(str(args["max_price"])) if args.get("max_price") else None
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
                p for p in products
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
''')

# ============================================================
# 4. UPDATE PRODUCT SERVICE (Add search method)
# ============================================================
write_file("app/services/product_service_enhanced.py", '''"""
Enhanced product search for Phase 8 Sales Agent.
Extends existing ProductService with multi-filter search capabilities.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.product import Product


def search_products(
    db: Session,
    store_id: uuid.UUID,
    query: str = "",
    category: Optional[str] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    limit: int = 5,
) -> list[Product]:
    """
    Search products with multiple filters.
    All queries are tenant-isolated by store_id.
    Only returns active products.
    """
    q = db.query(Product).filter(
        Product.store_id == store_id,
        Product.is_active == True,
    )

    # Text search (name, description, SKU)
    if query:
        search_term = f"%{query}%"
        q = q.filter(
            or_(
                Product.name.ilike(search_term),
                Product.description.ilike(search_term),
                Product.sku.ilike(search_term),
            )
        )

    # Category filter
    if category:
        q = q.filter(Product.category.ilike(f"%{category}%"))

    # Price range filters
    if min_price is not None:
        q = q.filter(Product.price >= min_price)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    return q.order_by(Product.created_at.desc()).limit(limit).all()
''')

print("\n=== Part 1 Complete ===")
print("Created:")
print("  - app/agent/tools/search_products.py (enhanced)")
print("  - app/agent/tools/get_product_details.py")
print("  - app/agent/tools/recommend_products.py")
print("  - app/services/product_service_enhanced.py")
print("\nNext: Register tools in agent.py and run tests")
