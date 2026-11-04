"""Recommend active, in-stock products using explicit catalog and price signals."""

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.agent.tools.search_products import normalize_product_search_text


class RecommendProductsTool(BaseTool):
    @property
    def name(self) -> str:
        return "recommend_products"

    @property
    def description(self) -> str:
        return (
            "Recommend active products that have inventory. Use this when the "
            "customer asks for alternatives, a cheaper option, or suggestions "
            "matching a stated need. Recommendations are grounded in catalog "
            "text, actual prices, and inventory; never imply an unsupported match."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "based_on_product_id": {
                    "type": "string",
                    "description": "Server-resolved reference product (optional)",
                },
                "customer_need": {
                    "type": "string",
                    "description": "Brief terms describing the customer's stated need",
                },
                "max_price": {
                    "type": "number",
                    "description": "Customer-stated maximum price, if known",
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
            based_on_variant_id = args.get("based_on_variant_id")
            customer_need = args.get("customer_need")
            if customer_need is not None and (
                not isinstance(customer_need, str)
                or not customer_need.strip()
                or len(customer_need.strip()) > 160
            ):
                return ToolResult(
                    success=False,
                    error="Customer need must be a short non-empty string.",
                    error_code="VALIDATION_ERROR",
                )
            max_price = None
            if "max_price" in args and args["max_price"] is not None:
                max_price = Decimal(str(args["max_price"]))
                if not max_price.is_finite() or max_price < 0:
                    return ToolResult(
                        success=False,
                        error="Maximum price must be a non-negative finite value.",
                        error_code="VALIDATION_ERROR",
                    )
            reason = args.get("reason", "general")
            if reason not in {
                "out_of_stock_alternative",
                "cheaper_option",
                "complementary",
                "general",
            }:
                return ToolResult(
                    success=False,
                    error="Unsupported recommendation reason.",
                    error_code="VALIDATION_ERROR",
                )
            raw_limit = args.get("limit", 3)
            if (
                isinstance(raw_limit, bool)
                or not isinstance(raw_limit, int)
                or not 1 <= raw_limit <= 10
            ):
                return ToolResult(
                    success=False,
                    error="Recommendation limit must be between 1 and 10.",
                    error_code="VALIDATION_ERROR",
                )
            limit = min(max(raw_limit, 1), 10)

            ref_product = None
            reference_price = None
            if based_on_id:
                try:
                    ref_product_id = uuid.UUID(str(based_on_id))
                except (ValueError, TypeError, AttributeError):
                    return ToolResult(
                        success=False,
                        error="Invalid reference product.",
                        error_code="INVALID_PRODUCT",
                    )
                ref_product = (
                    db.query(Product)
                    .filter(
                        Product.id == ref_product_id,
                        Product.store_id == store_id,
                        Product.is_active.is_(True),
                    )
                    .one_or_none()
                )
                if ref_product is None:
                    return ToolResult(
                        success=False,
                        error="Reference product not found.",
                        error_code="INVALID_PRODUCT",
                    )
                ref_price_query = (
                    db.query(
                        Product.base_price
                        + func.coalesce(ProductVariant.price_adjustment, 0)
                    )
                    .join(
                        ProductVariant,
                        ProductVariant.product_id == Product.id,
                    )
                    .filter(
                        Product.id == ref_product.id,
                        Product.store_id == store_id,
                        Product.is_active.is_(True),
                    )
                )
                if based_on_variant_id:
                    try:
                        reference_variant_id = uuid.UUID(
                            str(based_on_variant_id)
                        )
                    except (ValueError, TypeError, AttributeError):
                        return ToolResult(
                            success=False,
                            error="Invalid reference variant.",
                            error_code="INVALID_PRODUCT",
                        )
                    ref_price_query = ref_price_query.filter(
                        ProductVariant.id == reference_variant_id
                    )
                reference_price_row = ref_price_query.order_by(
                    (
                        Product.base_price
                        + func.coalesce(ProductVariant.price_adjustment, 0)
                    ).asc()
                ).first()
                if based_on_variant_id and reference_price_row is None:
                    return ToolResult(
                        success=False,
                        error="Reference variant does not belong to this product.",
                        error_code="INVALID_PRODUCT",
                    )
                reference_price = (
                    Decimal(str(reference_price_row[0]))
                    if reference_price_row is not None
                    else Decimal(str(ref_product.base_price))
                )
                if reason == "cheaper_option":
                    max_price = (
                        min(max_price, reference_price)
                        if max_price is not None
                        else reference_price
                    )

            actual_price = Product.base_price + func.coalesce(
                ProductVariant.price_adjustment, 0
            )
            query = (
                db.query(
                    Product,
                    func.sum(InventoryItem.quantity).label("available_quantity"),
                    func.min(actual_price).label("available_price"),
                )
                .join(ProductVariant, ProductVariant.product_id == Product.id)
                .join(
                    InventoryItem,
                    (InventoryItem.variant_id == ProductVariant.id)
                    & (InventoryItem.store_id == store_id),
                )
                .filter(
                    Product.store_id == store_id,
                    Product.is_active.is_(True),
                    InventoryItem.quantity > 0,
                )
                .group_by(Product.id)
            )
            if max_price is not None:
                query = query.filter(actual_price <= max_price)
            if reason == "cheaper_option" and reference_price is not None:
                query = query.filter(actual_price < reference_price)

            rows = query.all()
            reference_text = (
                f"{ref_product.name} {ref_product.description or ''}"
                if ref_product is not None
                else ""
            )
            need_text = customer_need or ""
            terms = self._terms(f"{reference_text} {need_text}")
            ranked = []
            for product, available_quantity, available_price in rows:
                if ref_product is not None and product.id == ref_product.id:
                    continue
                product_terms = self._terms(
                    f"{product.name} {product.description or ''}"
                )
                overlap = len(terms & product_terms)
                if (customer_need or ref_product is not None) and overlap == 0:
                    continue
                ranked.append(
                    (
                        product,
                        int(available_quantity or 0),
                        overlap,
                        Decimal(str(available_price)),
                    )
                )
            ranked.sort(
                key=lambda item: (
                    -item[2],
                    item[3],
                    item[0].name.casefold(),
                )
            )
            recommendations = ranked[:limit]
            if not recommendations:
                return ToolResult(
                    success=False,
                    data={"recommendations": [], "count": 0},
                    error="No in-stock products matched the available criteria.",
                    error_code="NO_RESULTS",
                )

            return ToolResult(
                success=True,
                data={
                    "recommendations": [
                        {
                            "id": str(product.id),
                            "name": product.name,
                            "price": str(available_price),
                            "currency": "DZD",
                            "is_available": available_quantity > 0,
                            "reason": reason,
                        }
                        for (
                            product,
                            available_quantity,
                            _overlap,
                            available_price,
                        ) in recommendations
                    ],
                    "count": len(recommendations),
                    "based_on": ref_product.name if ref_product else None,
                },
            )

        except (ArithmeticError, TypeError, ValueError):
            return ToolResult(
                success=False,
                error="Invalid recommendation criteria.",
                error_code="VALIDATION_ERROR",
            )

    @staticmethod
    def _terms(value: str) -> set[str]:
        normalized = normalize_product_search_text(value)
        return {
            token
            for token in re.findall(r"[\w]+", normalized, flags=re.UNICODE)
            if len(token) > 1
        }
