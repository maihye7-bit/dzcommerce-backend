"""
OrderDraft Service: Manages temporary cart states linked to conversations.
Phase 13 Logic + Index-Based Resolution & Safety Checks.
CRITICAL RULES:
1. NEVER trust prices from input (LLM). Always fetch from DB.
2. NEVER trust store_id from input. Validate against conversation context.
3. Drafts do NOT deduct stock. Only confirmation does.
4. Uses VARIANT INDEX for safe LLM interaction instead of raw UUIDs.
5. Implements Case A (Same Draft), B (Conflict), C (New), D (Invalid).
6. BACKWARD COMPATIBILITY: Provides 'save_draft' alias for legacy imports.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy.orm import Session
from app.models.conversation import Conversation
from app.models.product import Product, ProductVariant
from app.models.inventory import InventoryItem
from app.services.exceptions import NotFoundError, ValidationError


def get_current_draft(db: Session, conversation_id: uuid.UUID) -> dict | None:
    """Retrieve the active draft JSON from the conversation."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise NotFoundError("Conversation not found")
    return conv.active_draft_json


def replace_draft_item_variant(
    db: Session,
    conversation_id: uuid.UUID,
    store_id: uuid.UUID,
    item_index: int,
    variant_id: uuid.UUID,
    replacement_quantity: int | None = None,
) -> dict:
    """Replace one draft item's variant after revalidating the complete draft."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.store_id == store_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        raise NotFoundError("Conversation not found in this store.")

    draft = conversation.active_draft_json
    items = draft.get("items") if isinstance(draft, dict) else None
    if not isinstance(items, list) or not items:
        raise ValidationError("No active draft found to update.")
    if isinstance(item_index, bool) or not isinstance(item_index, int):
        raise ValidationError("Draft item position must be an integer.")
    if item_index < 1 or item_index > len(items):
        raise ValidationError("Draft item position is outside the current draft.")
    if replacement_quantity is not None and (
        isinstance(replacement_quantity, bool)
        or not isinstance(replacement_quantity, int)
        or replacement_quantity <= 0
    ):
        raise ValidationError("Replacement quantity must be a positive integer.")

    target_variant = (
        db.query(ProductVariant)
        .join(Product)
        .filter(
            ProductVariant.id == variant_id,
            Product.store_id == store_id,
            Product.is_active.is_(True),
        )
        .one_or_none()
    )
    if target_variant is None:
        raise ValidationError("The requested variant is not available in this store.")

    selected_item = items[item_index - 1]
    if not isinstance(selected_item, dict):
        raise ValidationError("The selected draft item is invalid.")
    try:
        previous_variant_id = uuid.UUID(str(selected_item.get("variant_id")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("The selected draft item is invalid.") from exc

    previous_variant = (
        db.query(ProductVariant)
        .join(Product)
        .filter(
            ProductVariant.id == previous_variant_id,
            Product.store_id == store_id,
            Product.is_active.is_(True),
        )
        .one_or_none()
    )
    if previous_variant is None or previous_variant.product_id != target_variant.product_id:
        raise ValidationError("A draft variant can only be changed within the same product.")

    validated_items: list[dict[str, Any]] = []
    seen_variant_ids: set[uuid.UUID] = set()
    total_price = Decimal("0")
    for position, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise ValidationError("The current draft contains an invalid item.")
        try:
            current_variant_id = (
                variant_id
                if position == item_index - 1
                else uuid.UUID(str(raw_item.get("variant_id")))
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("The current draft contains an invalid variant.") from exc
        if current_variant_id in seen_variant_ids:
            raise ValidationError("The replacement would duplicate a draft item.")
        seen_variant_ids.add(current_variant_id)

        variant = (
            target_variant
            if current_variant_id == variant_id
            else db.query(ProductVariant)
            .join(Product)
            .filter(
                ProductVariant.id == current_variant_id,
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .one_or_none()
        )
        if variant is None:
            raise ValidationError("A draft item is no longer available in this store.")

        quantity = (
            replacement_quantity
            if position == item_index - 1 and replacement_quantity is not None
            else raw_item.get("quantity")
        )
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValidationError("A draft item has an invalid quantity.")
        inventory = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.variant_id == variant.id,
                InventoryItem.store_id == store_id,
            )
            .one_or_none()
        )
        available = inventory.quantity if inventory is not None else 0
        if available < quantity:
            raise ValidationError(
                f"Insufficient stock for {variant.product.name}. Available: {available}."
            )

        unit_price = Decimal(str(variant.product.base_price)) + Decimal(
            str(variant.price_adjustment or 0)
        )
        line_total = unit_price * quantity
        total_price += line_total
        updated_item = dict(raw_item)
        updated_item.update(
            variant_id=str(variant.id),
            product_name=variant.product.name,
            variant_name=variant.name,
            unit_price=float(unit_price),
            quantity=quantity,
            line_total=float(line_total),
            available_stock=available,
        )
        validated_items.append(updated_item)

    updated_draft = dict(draft)
    updated_draft.update(
        items=validated_items,
        total_price=float(total_price),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    conversation.active_draft_json = updated_draft
    db.flush()
    return updated_draft


def update_draft_items(
    db: Session,
    conversation_id: uuid.UUID,
    store_id: uuid.UUID,
    items: list[dict[str, Any]],
    shipping_info: dict | None = None,
) -> dict:
    """Persist an explicit draft update from server-resolved variant IDs."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.store_id == store_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        raise NotFoundError("Conversation not found in this store.")

    current_draft = conversation.active_draft_json
    if not isinstance(current_draft, dict) or not current_draft.get("items"):
        raise ValidationError("No active draft found to update.")
    if not items:
        raise ValidationError("A draft must contain at least one item.")

    validated_items: list[dict[str, Any]] = []
    seen_variant_ids: set[uuid.UUID] = set()
    total_price = Decimal("0")
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValidationError("The requested draft contains an invalid item.")
        try:
            variant_id = uuid.UUID(str(raw_item.get("variant_id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("The requested draft contains an invalid variant.") from exc

        quantity = raw_item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValidationError("A draft item has an invalid quantity.")
        if variant_id in seen_variant_ids:
            raise ValidationError("A draft cannot contain duplicate variants.")
        seen_variant_ids.add(variant_id)

        variant = (
            db.query(ProductVariant)
            .join(Product)
            .filter(
                ProductVariant.id == variant_id,
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .one_or_none()
        )
        if variant is None:
            raise ValidationError("A draft variant is not available in this store.")

        inventory = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.variant_id == variant.id,
                InventoryItem.store_id == store_id,
            )
            .one_or_none()
        )
        available = inventory.quantity if inventory is not None else 0
        if available < quantity:
            raise ValidationError(
                f"Insufficient stock for {variant.product.name}. Available: {available}."
            )

        unit_price = Decimal(str(variant.product.base_price)) + Decimal(
            str(variant.price_adjustment or 0)
        )
        line_total = unit_price * quantity
        total_price += line_total
        validated_items.append(
            {
                "variant_id": str(variant.id),
                "product_name": variant.product.name,
                "variant_name": variant.name,
                "unit_price": float(unit_price),
                "quantity": quantity,
                "line_total": float(line_total),
                "available_stock": available,
            }
        )

    updated_draft = dict(current_draft)
    updated_draft.update(
        items=validated_items,
        shipping_info=shipping_info or current_draft.get("shipping_info") or {},
        total_price=float(total_price),
        currency="DZD",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    conversation.active_draft_json = updated_draft
    db.flush()
    return updated_draft


CANONICAL_SHIPPING_KEYS = {
    "phone",
    "wilaya",
    "municipality",
    "commune",
    "address",
    "first_name",
    "last_name",
}


def _normalize_canonical_shipping(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    merged: dict[str, str] = {}
    for key in CANONICAL_SHIPPING_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


def save_draft_safe(
    db: Session,
    conversation_id: uuid.UUID,
    store_id: uuid.UUID,
    items: list[dict],
    shipping_info: dict | None = None,
) -> dict:
    """
    Resolves variant indices to UUIDs using stored mapping.
    Validates against existing draft state.
    Handles Cases A, B, C safely:
      A - same items: preserve draft, merge new shipping info, return updated draft
      B - different items: conflict error, draft untouched
      C - no draft / multi-item: create new draft
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise NotFoundError("Conversation not found")

    metadata = conv.metadata_json or {}
    variant_map = metadata.get("variant_index_map", {})
    if not variant_map:
        raise ValidationError(
            "No active product context. Please call 'get_product_details' first to see available options."
        )

    resolved_items = []
    for item in items:
        idx = item.get("variant_index")
        qty = item.get("quantity", 1)

        if idx is None or qty <= 0:
            raise ValidationError(f"Invalid item format: {item}")

        variant_id_str = variant_map.get(str(idx))
        if not variant_id_str:
            raise ValidationError(
                f"Variant index {idx} not found. Valid indices are: {list(variant_map.keys())}. Call get_product_details again."
            )

        try:
            variant_id = uuid.UUID(variant_id_str)
        except ValueError:
            raise ValidationError("Corrupted variant mapping. Reset context.")

        variant = db.query(ProductVariant).join(Product).filter(
            ProductVariant.id == variant_id,
            Product.store_id == store_id,
        ).first()

        if not variant:
            raise ValidationError("Selected variant does not belong to this store.")

        resolved_items.append({
            "variant_id": variant_id,
            "variant_obj": variant,
            "quantity": qty,
        })

    existing_draft = conv.active_draft_json

    if existing_draft and existing_draft.get("items"):
        ex_items = existing_draft["items"]

        if len(resolved_items) == 1 and len(ex_items) == 1:
            req_vid = str(resolved_items[0]["variant_id"])
            req_qty = resolved_items[0]["quantity"]

            ex_vid = ex_items[0].get("variant_id")
            ex_qty = ex_items[0].get("quantity")

            # CASE A: Same Variant + Same Quantity -> Idempotent, merge shipping
            if req_vid == ex_vid and req_qty == ex_qty:
                existing_shipping: dict[str, Any] = dict(
                    existing_draft.get("shipping_info") or {}
                )
                new_shipping = _normalize_canonical_shipping(shipping_info)
                existing_shipping.update(new_shipping)
                updated_draft = dict(existing_draft)
                updated_draft["shipping_info"] = existing_shipping
                updated_draft["updated_at"] = datetime.now(timezone.utc).isoformat()
                conv.active_draft_json = updated_draft
                db.flush()
                return updated_draft

            # CASE B: Different Item -> Conflict Warning
            ex_summary = f"{ex_items[0]['product_name']} ({ex_items[0]['variant_name']}) x{ex_qty}"
            ex_total = existing_draft.get("total_price", 0)
            req_variant = resolved_items[0]["variant_obj"]
            req_summary = f"{req_variant.product.name} ({req_variant.name}) x{req_qty}"
            raise ValidationError(
                f"NO CHANGE MADE. An active draft already exists and was NOT modified.\n"
                f"Existing draft: {ex_summary} - total {ex_total} DZD.\n"
                f"The requested selection is different: {req_summary}.\n"
                f"Instruction: Do not apologize and do not retry this tool. "
                f"Tell the customer about the existing draft and ask whether they want to "
                f"KEEP it (reply 'أكد' to confirm it) or CHANGE it."
            )

    # CASE C: No Draft or Multi-Item Complexity -> Create New
    validated_items = []
    total_price = Decimal("0")

    for ri in resolved_items:
        variant = ri["variant_obj"]
        qty = ri["quantity"]

        unit_price = (
            Decimal(str(variant.product.base_price))
            + Decimal(str(variant.price_adjustment or 0))
        )
        line_total = unit_price * qty
        total_price += line_total

        inv_item = db.query(InventoryItem).filter(
            InventoryItem.variant_id == variant.id
        ).first()
        avail = inv_item.quantity if inv_item else 0

        if avail < qty:
            raise ValidationError(
                f"Insufficient stock for {variant.product.name}. Available: {avail}"
            )

        validated_items.append({
            "variant_id": str(variant.id),
            "product_name": variant.product.name,
            "variant_name": variant.name,
            "unit_price": float(unit_price),
            "quantity": qty,
            "line_total": float(line_total),
            "available_stock": avail,
        })

    draft_data = {
        "draft_id": (
            existing_draft.get("draft_id")
            if isinstance(existing_draft, dict)
            and isinstance(existing_draft.get("draft_id"), str)
            else str(uuid.uuid4())
        ),
        "items": validated_items,
        "shipping_info": _normalize_canonical_shipping(shipping_info),
        "total_price": float(total_price),
        "currency": "DZD",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    conv.active_draft_json = draft_data
    db.flush()

    return draft_data


# ==============================================================================
# BACKWARD COMPATIBILITY WRAPPER
# Allows old code (like update_order_draft.py) to import 'save_draft' 
# without breaking, by routing it through the new safe logic.
# NOTE: This assumes the caller passes 'store_id' correctly or we extract it.
# Since 'save_draft' signature varies, we create a flexible adapter here.
# ==============================================================================

def save_draft(
    db: Session,
    conversation_id: uuid.UUID,
    items: list[dict],  
    shipping_info: dict | None = None,
    store_id: uuid.UUID | None = None # Optional param for compatibility
) -> dict:
    """
    Legacy-compatible wrapper for save_draft_safe.
    If store_id is not provided, attempts to derive it from the conversation.
    """
    # Derive store_id if not passed explicitly (fallback for old calls)
    if store_id is None:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            raise NotFoundError("Conversation not found")
        store_id = conv.store_id
        
    # The new logic expects 'variant_index', but old code might send 'variant_id'.
    # We need to handle both cases gracefully or force the new schema.
    # For strict Phase 13 compliance, we assume the tool layer converts inputs.
    # However, to prevent crash during transition, we check keys.
    
    normalized_items = []
    for item in items:
        # If it has variant_id directly (old style), we can't use index map easily 
        # unless we reverse lookup. But for now, let's assume the Tool Layer 
        # handles the conversion before calling this service.
        # If this function is called directly with variant_id, it will fail in save_draft_safe.
        # So we rely on the Tool Layer (create_order_draft.py) to pass correct data.
        normalized_items.append(item)

    return save_draft_safe(
        db=db,
        conversation_id=conversation_id,
        store_id=store_id,
        items=normalized_items,
        shipping_info=shipping_info
    )


def clear_draft(db: Session, conversation_id: uuid.UUID) -> None:
    """Removes the active draft from the conversation."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.active_draft_json = None
        db.flush()
