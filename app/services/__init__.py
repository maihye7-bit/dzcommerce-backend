"""
Services package initialization.
"""
from app.services.customer_context_service import get_customer_context
from app.services.channel_service import handle_inbound_event
from app.services.cod_intelligence_service import calculate_risk_score as calculate_cod_risk
from app.services.attribute_normalizer import normalize_attributes, normalize_value
from app.services.webhook_processor import process_webhook_event
from app.services.webhook_security import verify_meta_signature as verify_signature
from app.services.usage_service import record_usage
from app.services.product_service import (
    get_product,
    list_products,
    search_products,
    create_product,
    update_product,
    delete_product,
    create_variant,
    update_variant,
)
from app.services.order_service import (
    get_order,
    list_orders,
    create_draft,
    add_item,
    update_item,
    remove_item,
    confirm_order,
    cancel_order,
    transition_status,
)
from app.services.order_draft_service import (
    get_current_draft,
    save_draft,
    save_draft_safe,
    clear_draft,
    update_draft_items,
    replace_draft_item_variant,
)
from app.services.inventory_service import (
    get_available_quantity,
    set_variant_stock,
    deduct_stock,
    restore_stock,
)
from app.services.lost_sales_service import (
    create_opportunity,
    get_open_opportunities,
    mark_as_followed_up,
    check_abandoned_drafts,
)
from app.services.pricing_config import get_pricing
from app.services.product_image_service import (
    create_product_image,
    replace_product_image,
    get_product_image,
    get_image_by_id,
    list_product_images,
    update_product_image,
    delete_product_image,
    set_primary_image,
    reorder_images,
    get_primary_image,
    mark_image_processing,
    get_images_pending_processing,
    validate_image_file,
    generate_storage_key,
    MAX_FILE_SIZE,
    ALLOWED_MIME_TYPES,
    MAX_IMAGES_PER_PRODUCT,
)

__all__ = [
    "get_customer_context",
    "handle_inbound_event",
    "calculate_cod_risk",
    "normalize_attributes",
    "normalize_value",
    "process_webhook_event",
    "verify_signature",
    "record_usage",
    "get_product",
    "list_products",
    "search_products",
    "create_product",
    "update_product",
    "delete_product",
    "create_variant",
    "update_variant",
    "get_order",
    "list_orders",
    "create_draft",
    "add_item",
    "update_item",
    "remove_item",
    "confirm_order",
    "cancel_order",
    "transition_status",
    "get_current_draft",
    "save_draft",
    "save_draft_safe",
    "clear_draft",
    "update_draft_items",
    "replace_draft_item_variant",
    "get_available_quantity",
    "set_variant_stock",
    "deduct_stock",
    "restore_stock",
    "create_opportunity",
    "get_open_opportunities",
    "mark_as_followed_up",
    "check_abandoned_drafts",
    "get_pricing",
    "create_product_image",
    "replace_product_image",
    "get_product_image",
    "get_image_by_id",
    "list_product_images",
    "update_product_image",
    "delete_product_image",
    "set_primary_image",
    "reorder_images",
    "get_primary_image",
    "mark_image_processing",
    "get_images_pending_processing",
    "validate_image_file",
    "generate_storage_key",
    "MAX_FILE_SIZE",
    "ALLOWED_MIME_TYPES",
    "MAX_IMAGES_PER_PRODUCT",
]