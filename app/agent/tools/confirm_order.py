"""
Confirm Order Tool: Finalizes the draft into a persistent Order.
"""
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.models.conversation import Conversation
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.services.exceptions import NotFoundError, ValidationError
from app.services.inventory_service import deduct_stock


class ConfirmOrderTool(BaseTool):

    @property
    def name(self) -> str:
        return "confirm_order"

    @property
    def description(self) -> str:
        return (
            "Confirms the current order draft and places the final order. "
            "This action DEDUCTS STOCK permanently. "
            "Use this ONLY after the customer writes the exact phrase 'أكد الطلب' "
            "in response to the verified order summary."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        if not context:
            return ToolResult(success=False, error="Missing confirmation context.")

        db: Session = context["db"]
        conversation_id = context.get("conversation_id")
        customer_id = context.get("customer_id")

        if not conversation_id or not customer_id:
            return ToolResult(
                success=False,
                error="Missing conversation or customer context.",
            )

        # Lock the conversation row so concurrent confirmations serialize.
        db.flush()
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.store_id == store_id,
            )
            .with_for_update()
            .first()
        )
        if not conv:
            print(f"❌ CONFIRM_FAIL: Conv {conversation_id} not found for store {store_id}.")
            return ToolResult(
                success=False,
                error="Internal State Error: Conversation lost.",
            )

        if conv.customer_id != customer_id:
            return ToolResult(
                success=False,
                error="Conversation does not belong to this customer.",
            )

        draft_data = conv.active_draft_json
        if not isinstance(draft_data, dict) or not draft_data.get("items"):
            return ToolResult(
                success=True,
                data={
                    "already_confirmed": True,
                    "message": "There is no active draft to confirm; it may already have been confirmed.",
                },
            )

        pending_confirmation = (conv.metadata_json or {}).get(
            "confirmation_pending"
        )
        draft_id = draft_data.get("draft_id")
        if (
            not isinstance(draft_id, str)
            or not isinstance(pending_confirmation, dict)
            or pending_confirmation.get("draft_id") != draft_id
        ):
            return ToolResult(
                success=False,
                error="This draft is not awaiting customer confirmation.",
                error_code="CONFIRMATION_NOT_PENDING",
            )

        items = draft_data["items"]
        if not isinstance(items, list):
            raise ValidationError("Invalid order draft structure.")

        total_price = Decimal("0")
        created_items = []

        for item in items:
            if not isinstance(item, dict):
                raise ValidationError("Invalid item structure in draft.")

            variant_id_str = item.get("variant_id")
            try:
                variant_id = uuid.UUID(str(variant_id_str))
            except (ValueError, TypeError, AttributeError):
                raise ValidationError(f"Invalid variant ID format: {variant_id_str}")

            raw_quantity = item.get("quantity", 1)
            if isinstance(raw_quantity, bool):
                raise ValidationError(f"Invalid item quantity: {raw_quantity}")
            try:
                quantity = int(raw_quantity)
            except (ValueError, TypeError, OverflowError):
                raise ValidationError(f"Invalid item quantity: {raw_quantity}")
            if quantity <= 0 or str(quantity) != str(raw_quantity).strip():
                raise ValidationError(f"Invalid item quantity: {raw_quantity}")

            # Fetch authoritative variant/product data under this tenant.
            variant = (
                db.query(ProductVariant)
                .join(Product, ProductVariant.product_id == Product.id)
                .filter(
                    ProductVariant.id == variant_id,
                    Product.store_id == store_id,
                    Product.is_active.is_(True),
                )
                .first()
            )
            if not variant:
                raise NotFoundError(
                    f"Variant {variant_id} not found or unavailable for this store."
                )

            product = variant.product
            unit_price = (
                Decimal(str(product.base_price))
                + Decimal(str(variant.price_adjustment or 0))
            )
            total_price += unit_price * quantity

            # deduct_stock locks and validates inventory; the caller commits
            # order, items, stock, and draft state together.
            deduct_stock(
                db=db,
                store_id=store_id,
                variant_id=variant_id,
                quantity=quantity,
            )

            created_items.append({
                "product_id": product.id,
                "variant_id": variant.id,
                "quantity": quantity,
                "unit_price": unit_price,
            })

        raw_shipping = draft_data.get("shipping_info")
        if not isinstance(raw_shipping, dict):
            raw_shipping = {}

        new_order = Order(
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            status=OrderStatus.CONFIRMED,
            subtotal=total_price,
            total=total_price,
            shipping_cost=Decimal("0"),
            shipping_address=json.dumps(raw_shipping),
            wilaya=raw_shipping.get("wilaya"),
        )
        db.add(new_order)
        db.flush()

        for item in created_items:
            db.add(OrderItem(
                order_id=new_order.id,
                product_id=item["product_id"],
                variant_id=item["variant_id"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
            ))

        conv.active_draft_json = None
        metadata = dict(conv.metadata_json or {})
        metadata.pop("confirmation_pending", None)
        conv.metadata_json = metadata
        db.flush()

        return ToolResult(
            success=True,
            data={
                "order_id": str(new_order.id),
                "order_number": f"ORD-{uuid.uuid4().hex[:8].upper()}",
                "status": "confirmed",
                "total_amount": float(total_price),
                "message": "Order confirmed successfully.",
            },
        )
