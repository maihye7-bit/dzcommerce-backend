from __future__ import annotations

import uuid
import re
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agent.tools.search_products import normalize_product_search_text
from app.models.conversation import Conversation
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductVariant
from app.services.attribute_normalizer import normalize_attributes, normalize_value


logger = logging.getLogger(__name__)

_LEGACY_COLOR_ALIASES = {
    "سودا": "black",
    "سوداء": "black",
}


class CommerceStage(str, Enum):
    EMPTY = "EMPTY"
    PRODUCT_CANDIDATES = "PRODUCT_CANDIDATES" # New Stage for multiple results
    PRODUCT_SELECTED = "PRODUCT_SELECTED"
    VARIANT_SELECTED = "VARIANT_SELECTED"
    DRAFT_PENDING = "DRAFT_PENDING"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"


class AllowedAction(str, Enum):
    SEARCH_PRODUCTS = "EXECUTE_TOOL:search_products"
    LIST_CATALOG_PRODUCTS = "EXECUTE_TOOL:list_catalog_products"
    GET_PRODUCT_DETAILS = "EXECUTE_TOOL:get_product_details"
    CREATE_ORDER_DRAFT_TOOL = "EXECUTE_TOOL:create_order_draft"
    UPDATE_ORDER_DRAFT_TOOL = "EXECUTE_TOOL:update_order_draft"
    CREATE_DRAFT = "CALL_SERVICE:create_draft"
    UPDATE_DRAFT = "CALL_SERVICE:update_draft"
    CONFIRM_ORDER = "EXECUTE_TOOL:confirm_order"
    RESOLVE_VARIANT = "CALL_SERVICE:resolve_variant"
    RE_SEARCH_OR_CONFIRM_CHANGE = "RESPOND:text_only"
    ASK_FOR_CLARIFICATION = "RESPOND:text_only"
    BLOCK_UNLESS_EXPLICIT_RESET = "RESPOND:text_only"
    INFO_ALREADY_CONFIRMED = "RESPOND:text_only"
    ERROR_NO_DRAFT_YET = "RESPOND:text_only"
    UPDATE_SELECTION = "CALL_SERVICE:update_selection"
    LIST_CANDIDATES = "RESPOND:text_only" # Action to show list
    HANDLE_OBJECTION = "RESPOND:text_only"
    ADVANCE_PURCHASE = "RESPOND:text_only"
    NATURAL_RESPONSE = "RESPOND:text_only"


@dataclass
class ResolutionResult:
    allowed_action: str
    resolved_entities: dict[str, Any] = field(default_factory=dict)
    context_updates: dict[str, Any] = field(default_factory=dict)
    response_hint: str = ""


class CommerceResolver:
    """
    Pure decision layer between Qwen NLU output and business execution.
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve(
        self, 
        nlu_output: dict[str, Any], 
        current_state: dict[str, Any],
        store_id: uuid.UUID
    ) -> ResolutionResult:
        state = current_state or {}
        
        # 1. Determine Stage from DB Facts
        stage = self._get_current_stage_from_db(state)

        intent = (nlu_output or {}).get("intent") or (nlu_output or {}).get("intent_guess", "unknown")
        raw_attributes = (nlu_output or {}).get("attributes") or {}
        attributes = normalize_attributes(raw_attributes) if isinstance(raw_attributes, dict) else {}
        quantity = (nlu_output or {}).get("quantity") or 1
        product_mention = (nlu_output or {}).get("product_mention")
        confirmation_phrase = bool((nlu_output or {}).get("confirmation_phrase", False))
        language = (nlu_output or {}).get("language", "ar")

        def text(arabic: str, french: str) -> str:
            return french if language == "fr" else arabic

        # Base context to preserve history
        base_context = {
            "commerce_stage": stage.value,
            "selected_product_id": state.get("selected_product_id"),
            "selected_variant_id": state.get("selected_variant_id"),
            "selected_attributes": state.get("selected_attributes") or {},
            "candidate_product_ids": state.get("candidate_product_ids") or [],
            "last_intent": intent,
            "last_nlu": nlu_output or {},
        }

        if (nlu_output or {}).get("availability_query") is True:
            return self._resolve_variant_availability(
                store_id=store_id,
                state=state,
                attributes=attributes,
                language=language,
            )

        # ---------------------------------------------------------
        # DECISION MATRIX
        # ---------------------------------------------------------

        if intent == "catalog_browse":
            return ResolutionResult(
                allowed_action=AllowedAction.LIST_CATALOG_PRODUCTS.value,
                resolved_entities={},
                context_updates=base_context,
                response_hint=text(
                    "سأعرض لك بعض المنتجات المسجلة في المتجر.",
                    "Voici quelques produits répertoriés dans la boutique.",
                ),
            )

        # Handle price objections - acknowledge and offer alternatives or ask budget
        if intent == "objection_handling" or intent == "OBJECTION_HANDLING":
            selected_product_id = state.get("selected_product_id")
            selected_product_name = state.get("selected_product_name") or state.get("last_product_name")
            selected_variant_id = state.get("selected_variant_id")

            if selected_product_id:
                # Customer is objecting to a specific product/variant they've seen
                return ResolutionResult(
                    allowed_action=AllowedAction.HANDLE_OBJECTION.value,
                    resolved_entities={
                        "product_id": selected_product_id,
                        "product_name": selected_product_name,
                        "variant_id": selected_variant_id,
                    },
                    context_updates={**base_context, "last_objection": "price"},
                    response_hint=text(
                        f"فهمت، السعر قد يكون غالي. عندك ميزانية معينة نبحث فيها؟ أو نلاقي بديل؟",
                        f"Je comprends, le prix est peut-être élevé. Avez-vous un budget précis ou cherchons-nous une alternative ?",
                    ),
                )
            else:
                # General objection without product context
                return ResolutionResult(
                    allowed_action=AllowedAction.HANDLE_OBJECTION.value,
                    resolved_entities={},
                    context_updates=base_context,
                    response_hint=text(
                        "فهمت، فين تحب نلقاو حاجة تناسبك أكثر؟",
                        "Je comprends, qu'est-ce qui vous conviendrait mieux ?",
                    ),
                )

        if (
            intent == "order_create"
            and isinstance(product_mention, str)
            and product_mention.strip()
            and stage in {
                CommerceStage.PRODUCT_SELECTED,
                CommerceStage.VARIANT_SELECTED,
            }
        ):
            selected_product_id = self._parse_uuid(state.get("selected_product_id"))
            selected_product = (
                self.db.query(Product)
                .filter(
                    Product.id == selected_product_id,
                    Product.store_id == store_id,
                    Product.is_active.is_(True),
                )
                .one_or_none()
                if selected_product_id is not None
                else None
            )
            if selected_product is not None:
                mentioned_name = normalize_product_search_text(product_mention)
                selected_name = normalize_product_search_text(selected_product.name)
                if (
                    mentioned_name
                    and selected_name
                    and mentioned_name not in selected_name
                    and selected_name not in mentioned_name
                ):
                    return ResolutionResult(
                        allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                        resolved_entities={"query": product_mention},
                        context_updates=base_context,
                        response_hint=text(
                            "سأتحقق من المنتج الذي ذكرته قبل متابعة الطلب.",
                            "Je vérifie le produit que vous venez de mentionner avant de continuer.",
                        ),
                    )

        if stage == CommerceStage.EMPTY:
            if intent == "product_search" and product_mention:
                return ResolutionResult(
                    allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                    resolved_entities={"query": product_mention},
                    context_updates=base_context,
                    response_hint=text(
                        "سأبحث عن المنتج الذي ذكرته.",
                        "Je recherche le produit que vous avez mentionné.",
                    ),
                )
            if intent == "order_create" and product_mention:
                return ResolutionResult(
                    allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                    resolved_entities={"query": product_mention},
                    context_updates=base_context,
                    response_hint=text(
                        "سأبحث عن المنتج الذي تريد طلبه، ثم نتحقق من خياراته.",
                        "Je recherche le produit souhaité, puis nous vérifierons ses options.",
                    ),
                )
            if intent == "order_create":
                return ResolutionResult(
                    allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                    resolved_entities={},
                    context_updates=base_context,
                    response_hint=text(
                        "نبدأ بتحديد المنتج: أرسل اسمه أو اطلب عرض المنتجات المتاحة في المتجر.",
                        "Pour commencer la commande, indiquez le produit ou demandez à voir le catalogue.",
                    ),
                )
            return ResolutionResult(
                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                resolved_entities={},
                context_updates=base_context,
                response_hint=text(
                    "ما هو المنتج الذي تبحث عنه؟",
                    "Quel produit recherchez-vous ?",
                ),
            )

        if stage == CommerceStage.PRODUCT_CANDIDATES:
            candidate_matches = self._match_candidate_products(
                store_id,
                state.get("candidate_product_ids") or [],
                product_mention,
            )
            if len(candidate_matches) == 1:
                product = candidate_matches[0]
                selected_context = {
                    **base_context,
                    "selected_product_id": str(product.id),
                    "selected_product_name": product.name,
                    "last_product_id": str(product.id),
                    "last_product_name": product.name,
                    "candidate_product_ids": [],
                    "selected_variant_id": None,
                    "selected_attributes": {},
                    "variant_index_map": {},
                    "commerce_stage": CommerceStage.PRODUCT_SELECTED.value,
                }
                return ResolutionResult(
                    allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                    resolved_entities={"product_id": str(product.id)},
                    context_updates=selected_context,
                    response_hint=text(
                        f"سأعرض تفاصيل {product.name}.",
                        f"Je vous présente les détails de {product.name}.",
                    ),
                )

            if intent == "variant_selection" or intent == "order_create":
                return ResolutionResult(
                    allowed_action=AllowedAction.LIST_CANDIDATES.value,
                    resolved_entities={},
                    context_updates=base_context,
                    response_hint=text(
                        "حدّد اسم المنتج الذي تريد معرفة تفاصيله من القائمة.",
                        "Indiquez le nom du produit dont vous souhaitez voir les détails.",
                    ),
                )
            elif intent == "product_search":
                if not product_mention or not product_mention.strip():
                    return self._default_result(base_context)
                return ResolutionResult(
                    allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                    resolved_entities={"query": product_mention},
                    context_updates=base_context,
                    response_hint=text(
                        "سأبحث عن المنتج الذي ذكرته.",
                        "Je recherche le produit que vous avez mentionné.",
                    ),
                )
            return self._default_result(base_context)

        if stage == CommerceStage.PRODUCT_SELECTED:
            prod_id_str = state.get("selected_product_id")

            if intent == "product_details":
                return ResolutionResult(
                    allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                    resolved_entities={"product_id": prod_id_str},
                    context_updates=base_context,
                    response_hint=text(
                        "سأعرض لك تفاصيل المنتج والخيارات المتاحة.",
                        "Voici les détails du produit et les options disponibles.",
                    ),
                )
            
            if intent == "variant_selection":
                if not prod_id_str:
                     return self._error_result(base_context, "No product selected.")
                
                try:
                    prod_uuid = uuid.UUID(prod_id_str)
                except ValueError:
                    return self._error_result(base_context, "Invalid product ID format.")

                variant_index = nlu_output.get("variant_index")
                if isinstance(variant_index, int) and not isinstance(
                    variant_index, bool
                ):
                    displayed_product_id = state.get(
                        "variant_index_map_product_id"
                    )
                    index_map = state.get("variant_index_map")
                    mapped_variant_id = (
                        index_map.get(str(variant_index))
                        if displayed_product_id == str(prod_uuid)
                        and isinstance(index_map, dict)
                        else None
                    )
                    variant_uuid = self._parse_uuid(mapped_variant_id)
                    variant = (
                        self.db.query(ProductVariant)
                        .join(Product)
                        .filter(
                            ProductVariant.id == variant_uuid,
                            ProductVariant.product_id == prod_uuid,
                            Product.store_id == store_id,
                            Product.is_active.is_(True),
                        )
                        .one_or_none()
                        if variant_uuid is not None
                        else None
                    )
                    if variant is None:
                        return ResolutionResult(
                            allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                            resolved_entities={
                                "product_id": str(prod_uuid),
                                "suppress_auto_selection": True,
                            },
                            context_updates=base_context,
                            response_hint=text(
                                "قائمة الخيارات لم تعد صالحة. سأعرض الخيارات الحالية؛ اختر رقمًا منها.",
                                "La liste des options n’est plus valide. Voici les options actuelles ; choisissez un numéro.",
                            ),
                        )
                else:
                    variant = self._resolve_variant_from_attributes(
                        store_id,
                        prod_uuid,
                        attributes,
                    )
                
                if variant:
                    stock = self._get_stock_count(store_id, variant.id)
                    if stock is None or stock <= 0:
                        return ResolutionResult(
                            allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                            resolved_entities={},
                            context_updates={},
                            response_hint=text(
                                (
                                    "الخيار غير متوفر حاليًا."
                                    if stock == 0
                                    else "الخيار موجود، يجب التحقق من المخزون قبل تأكيد اختياره."
                                ),
                                (
                                    "L’option est actuellement indisponible."
                                    if stock == 0
                                    else "L’option existe, mais son stock doit être vérifié avant de confirmer ce choix."
                                ),
                            ),
                        )
                    logger.info(
                        "Resolved variant %s for product %s in store %s",
                        variant.id,
                        prod_uuid,
                        store_id,
                    )
                    new_ctx = {
                        **base_context,
                        "selected_variant_id": str(variant.id),
                        "selected_attributes": attributes,
                        "commerce_stage": CommerceStage.VARIANT_SELECTED.value
                    }
                    return ResolutionResult(
                        allowed_action=AllowedAction.RESOLVE_VARIANT.value,
                        resolved_entities={
                            "product_id": str(prod_uuid),
                            "variant_id": str(variant.id),
                            "price": float(self._get_price_for_variant(store_id, variant)),
                            "stock": stock,
                        },
                        context_updates=new_ctx,
                        response_hint=text(
                            f"وجدت الخيار {variant.name}. يمكنك طلبه إذا رغبت.",
                            f"J’ai trouvé l’option {variant.name}. Vous pouvez la commander.",
                        ),
                    )
                else:
                    return ResolutionResult(
                        allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                        resolved_entities={"product_id": str(prod_uuid)},
                        context_updates=base_context,
                        response_hint=text(
                            "سأعرض لك الخيارات المتاحة لهذا المنتج.",
                            "Voici les options disponibles pour ce produit.",
                        ),
                    )

            elif intent == "order_create" or intent == "purchase_intent" or intent == "PURCHASE_INTENT":
                var_id_str = state.get("selected_variant_id")
                if var_id_str:
                     return self._prepare_draft_creation(store_id, prod_id_str, var_id_str, quantity, base_context)
                else:
                     product_uuid = self._parse_uuid(prod_id_str)
                     product = (
                         self.db.query(Product)
                         .filter(
                             Product.id == product_uuid,
                             Product.store_id == store_id,
                             Product.is_active.is_(True),
                         )
                         .one_or_none()
                         if product_uuid is not None
                         else None
                     )
                     if product is not None:
                         variants = (
                             self.db.query(ProductVariant)
                             .filter(ProductVariant.product_id == product.id)
                             .order_by(
                                 ProductVariant.created_at.asc(),
                                 ProductVariant.id.asc(),
                             )
                             .all()
                         )
                         available_variants = [
                             variant
                             for variant in variants
                             if (self._get_stock_count(store_id, variant.id) or 0) > 0
                         ]
                         if len(variants) == 1 and self._get_stock_count(
                             store_id, variants[0].id
                         ) is None:
                             return ResolutionResult(
                                 allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                                 resolved_entities={},
                                 context_updates=base_context,
                                 response_hint=text(
                                     "مخزون هذا الخيار غير مسجل، لذلك لا أستطيع إعداد المسودة قبل التحقق من توفره.",
                                     "Le stock de cette option n’est pas renseigné ; je ne peux pas préparer le brouillon avant d’en vérifier la disponibilité.",
                                 ),
                             )
                         if len(available_variants) == 1:
                             selected_variant = available_variants[0]
                             selected_context = {
                                 **base_context,
                                 "selected_product_id": str(product.id),
                                 "selected_variant_id": str(selected_variant.id),
                                 "selected_attributes": (
                                     selected_variant.attributes_json
                                     if isinstance(
                                         selected_variant.attributes_json, dict
                                     )
                                     else {}
                                 ),
                                 "commerce_stage": (
                                     CommerceStage.VARIANT_SELECTED.value
                                 ),
                             }
                             return self._prepare_draft_creation(
                                 store_id,
                                 str(product.id),
                                 str(selected_variant.id),
                                 quantity,
                                 selected_context,
                             )
                     return ResolutionResult(
                        allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                        resolved_entities={"product_id": prod_id_str},
                        context_updates=base_context,
                         response_hint=text(
                             "يرجى اختيار اللون أو المقاس أولًا.",
                             "Veuillez d’abord choisir la couleur ou la taille.",
                         ),
                    )

            elif intent == "product_search":
                 return ResolutionResult(
                     allowed_action=(
                         AllowedAction.SEARCH_PRODUCTS.value
                         if product_mention and product_mention.strip()
                         else AllowedAction.RE_SEARCH_OR_CONFIRM_CHANGE.value
                     ),
                     resolved_entities={"query": product_mention} if product_mention else {},
                     context_updates=base_context,
                     response_hint=(
                         text(
                             "يبدو أنك تبحث عن منتج آخر. سأبحث عنه.",
                             "Vous cherchez un autre produit. Je lance la recherche.",
                         )
                         if product_mention
                         else text(
                             "يبدو أنك تريد منتجًا آخر. ما المنتج الذي أبحث عنه؟",
                             "Vous souhaitez changer de produit. Lequel recherchez-vous ?",
                         )
                     ),
                )

            return self._default_result(base_context)

        if stage == CommerceStage.VARIANT_SELECTED:
            prod_id_str = state.get("selected_product_id")
            var_id_str = state.get("selected_variant_id")

            if intent == "product_details":
                product_uuid = self._parse_uuid(prod_id_str)
                variant_uuid = self._parse_uuid(var_id_str)
                if product_uuid is None or variant_uuid is None:
                    return self._error_result(
                        base_context,
                        "Selected item is no longer available.",
                    )
                variant = (
                    self.db.query(ProductVariant)
                    .join(Product)
                    .filter(
                        ProductVariant.id == variant_uuid,
                        ProductVariant.product_id == product_uuid,
                        Product.store_id == store_id,
                        Product.is_active.is_(True),
                    )
                    .one_or_none()
                )
                if variant is None:
                    return self._error_result(
                        base_context,
                        "Selected item is no longer available.",
                    )
                return ResolutionResult(
                    allowed_action=AllowedAction.RESOLVE_VARIANT.value,
                    resolved_entities={
                        "product_id": str(product_uuid),
                        "variant_id": str(variant_uuid),
                        "price": float(self._get_price_for_variant(store_id, variant)),
                        "stock": self._get_stock_count(store_id, variant_uuid),
                    },
                    context_updates=base_context,
                    response_hint=text(
                        "سأتحقق من سعر الخيار الذي اخترته.",
                        "Je vérifie le prix de l’option sélectionnée.",
                    ),
                )

            if intent == "order_create":
                if not var_id_str:
                    return self._error_result(base_context, "No variant selected.")
                return self._prepare_draft_creation(store_id, prod_id_str, var_id_str, quantity, base_context)

            # Handle purchase intent when variant is already selected - advance to draft creation
            if intent == "purchase_intent" or intent == "PURCHASE_INTENT":
                if var_id_str:
                    return self._prepare_draft_creation(store_id, prod_id_str, var_id_str, quantity, base_context)
                else:
                    return ResolutionResult(
                        allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                        resolved_entities={"product_id": prod_id_str},
                        context_updates=base_context,
                        response_hint=text(
                            "باش نمشيو للطلب، نحتاج تختار اللون أو المقاس أولاً.",
                            "Pour passer commande, il faut d'abord choisir la couleur ou la taille.",
                        ),
                    )

            elif intent == "variant_selection":
                product_uuid = self._parse_uuid(prod_id_str)
                if product_uuid is None:
                    return self._error_result(base_context, "Invalid product ID format.")
                variant = self._resolve_variant_from_attributes(
                    store_id,
                    product_uuid,
                    attributes,
                )
                if variant is None:
                    return ResolutionResult(
                        allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                        resolved_entities={},
                        context_updates={},
                        response_hint=text(
                            "لم أجد خيارًا مطابقًا، ولم أغيّر اختيارك الحالي.",
                            "Je n’ai pas trouvé d’option correspondante ; votre choix actuel reste inchangé.",
                        ),
                    )
                stock = self._get_stock_count(store_id, variant.id)
                if stock is None or stock <= 0:
                    return ResolutionResult(
                        allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                        resolved_entities={},
                        context_updates={},
                        response_hint=text(
                            (
                                "الخيار غير متوفر حاليًا."
                                if stock == 0
                                else "الخيار موجود، يجب التحقق من المخزون قبل تأكيد اختياره."
                            ),
                            (
                                "L’option est actuellement indisponible."
                                if stock == 0
                                else "L’option existe, mais son stock doit être vérifié avant de confirmer ce choix."
                            ),
                        ),
                    )
                updated_context = {
                    **base_context,
                    "selected_variant_id": str(variant.id),
                    "selected_attributes": (
                        variant.attributes_json
                        if isinstance(variant.attributes_json, dict)
                        else {}
                    ),
                    "commerce_stage": CommerceStage.VARIANT_SELECTED.value,
                }
                return ResolutionResult(
                    allowed_action=AllowedAction.RESOLVE_VARIANT.value,
                    resolved_entities={
                        "product_id": str(product_uuid),
                        "variant_id": str(variant.id),
                        "price": float(self._get_price_for_variant(store_id, variant)),
                        "stock": stock,
                    },
                    context_updates=updated_context,
                    response_hint=text(
                        f"تم تحديث اختيارك إلى {variant.name}.",
                        f"La sélection a été mise à jour : {variant.name}.",
                    ),
                )
            
            elif intent == "order_confirm":
                 return self._error_result(
                     base_context,
                     "لا يمكن تأكيد الطلب قبل إنشاء مسودة. قل «ديرلي طلب» أولًا.",
                 )

            return self._default_result(base_context)

        if stage == CommerceStage.DRAFT_PENDING:
            draft_product_id = state.get("selected_product_id")
            if not draft_product_id:
                draft_product = self._get_draft_product(store_id, state)
                if draft_product is not None:
                    draft_product_id = str(draft_product.id)

            if intent == "order_create":
                draft_action = nlu_output.get("draft_action")
                if draft_action in {"remove", "set", "replace"}:
                    return ResolutionResult(
                        allowed_action=AllowedAction.UPDATE_ORDER_DRAFT_TOOL.value,
                        resolved_entities={},
                        context_updates=base_context,
                        response_hint=text(
                            "سأحدّث مسودة الطلب.",
                            "Je vais mettre à jour votre commande provisoire.",
                        ),
                    )

                if nlu_output.get("idempotent_order_request") is True:
                    return ResolutionResult(
                        allowed_action=AllowedAction.NATURAL_RESPONSE.value,
                        resolved_entities={},
                        context_updates=base_context,
                        response_hint=text(
                            "مسودة طلبك محفوظة بالفعل ولم يتم تأكيدها. "
                            "راجع ملخصها وأكد الطلب فقط إذا كنت موافقًا.",
                            "Votre brouillon est déjà enregistré et n’est pas "
                            "confirmé. Vérifiez le récapitulatif et confirmez "
                            "uniquement si vous êtes d’accord.",
                        ),
                    )

                product_uuid = self._parse_uuid(draft_product_id)
                if product_uuid is None:
                    return ResolutionResult(
                        allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                        resolved_entities={},
                        context_updates=base_context,
                        response_hint=text(
                            "حدد المنتج والخيار الذي تريد إضافته إلى الطلب.",
                            "Indiquez le produit et l’option à ajouter à la commande.",
                        ),
                    )

                if product_mention:
                    product = (
                        self.db.query(Product)
                        .filter(
                            Product.id == product_uuid,
                            Product.store_id == store_id,
                            Product.is_active.is_(True),
                        )
                        .one_or_none()
                    )
                    mention = normalize_product_search_text(product_mention)
                    selected_name = normalize_product_search_text(
                        product.name if product is not None else None
                    )
                    if (
                        product is None
                        or not mention
                        or mention not in selected_name
                        and selected_name not in mention
                    ):
                        return ResolutionResult(
                            allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                            resolved_entities={"query": product_mention},
                            context_updates=base_context,
                            response_hint=text(
                                "سأبحث عن المنتج الذي ذكرته دون تغيير مسودة طلبك.",
                                "Je recherche le produit mentionné sans modifier votre commande provisoire.",
                            ),
                        )

                variant_uuid = self._parse_uuid(state.get("selected_variant_id"))
                variant = (
                    self.db.query(ProductVariant)
                    .join(Product)
                    .filter(
                        ProductVariant.id == variant_uuid,
                        ProductVariant.product_id == product_uuid,
                        Product.store_id == store_id,
                        Product.is_active.is_(True),
                    )
                    .one_or_none()
                    if variant_uuid is not None
                    else None
                )
                if variant is None:
                    return ResolutionResult(
                        allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                        resolved_entities={"product_id": str(product_uuid)},
                        context_updates=base_context,
                        response_hint=text(
                            "اختر خيارًا من المنتج قبل إضافته إلى مسودة الطلب.",
                            "Choisissez une option du produit avant de l’ajouter à la commande.",
                        ),
                    )

                return ResolutionResult(
                    allowed_action=AllowedAction.UPDATE_ORDER_DRAFT_TOOL.value,
                    resolved_entities={
                        "action": "add",
                        "variant_id": str(variant.id),
                        "quantity": quantity,
                    },
                    context_updates=base_context,
                    response_hint=text(
                        "توجد مسودة للطلب. سأضيف المنتج إليها.",
                        "Une commande provisoire existe déjà. Je vais y ajouter le produit.",
                    ),
                )

            if intent == "product_search" and product_mention:
                return ResolutionResult(
                    allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
                    resolved_entities={"query": product_mention},
                    context_updates=base_context,
                    response_hint=text(
                        "سأبحث عن المنتج الذي ذكرته، مع إبقاء مسودة طلبك كما هي.",
                        "Je recherche le produit mentionné sans modifier votre commande provisoire.",
                    ),
                )

            if intent == "product_details":
                product_id = draft_product_id
                if product_mention:
                    candidate_ids = state.get("candidate_product_ids") or []
                    candidate_matches = self._match_candidate_products(
                        store_id,
                        candidate_ids,
                        product_mention,
                    )
                    if candidate_ids:
                        product_id = (
                            str(candidate_matches[0].id)
                            if len(candidate_matches) == 1
                            else None
                        )
                    elif product_id:
                        selected_uuid = self._parse_uuid(product_id)
                        selected_product = (
                            self.db.query(Product)
                            .filter(
                                Product.id == selected_uuid,
                                Product.store_id == store_id,
                                Product.is_active.is_(True),
                            )
                            .one_or_none()
                            if selected_uuid is not None
                            else None
                        )
                        mention = normalize_product_search_text(product_mention)
                        selected_name = normalize_product_search_text(
                            selected_product.name
                            if selected_product is not None
                            else None
                        )
                        if (
                            selected_product is None
                            or not mention
                            or mention not in selected_name
                            and selected_name not in mention
                        ):
                            product_id = None

                if product_id:
                    product_uuid = self._parse_uuid(product_id)
                    product = (
                        self.db.query(Product)
                        .filter(
                            Product.id == product_uuid,
                            Product.store_id == store_id,
                            Product.is_active.is_(True),
                        )
                        .one_or_none()
                        if product_uuid is not None
                        else None
                    )
                    if product is not None:
                        return ResolutionResult(
                            allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                            resolved_entities={"product_id": str(product.id)},
                            context_updates=base_context,
                            response_hint=text(
                                "سأعرض لك تفاصيل المنتج والخيارات المتاحة.",
                                "Voici les détails du produit et les options disponibles.",
                            ),
                        )

            if intent == "variant_selection" and draft_product_id:
                product_uuid = self._parse_uuid(draft_product_id)
                variant_id = None
                variant_index = nlu_output.get("variant_index")
                if product_uuid is not None and isinstance(variant_index, int):
                    index_map = state.get("variant_index_map") or {}
                    if (
                        str(state.get("variant_index_map_product_id"))
                        == str(product_uuid)
                        and str(variant_index) in index_map
                    ):
                        variant_id = self._parse_uuid(index_map[str(variant_index)])
                if product_uuid is not None and variant_id is None:
                    variant = self._resolve_variant_from_attributes(
                        store_id,
                        product_uuid,
                        attributes,
                    )
                    if variant is not None:
                        variant_id = variant.id

                if product_uuid is not None and variant_id is not None:
                    variant = (
                        self.db.query(ProductVariant)
                        .join(Product)
                        .filter(
                            ProductVariant.id == variant_id,
                            ProductVariant.product_id == product_uuid,
                            Product.store_id == store_id,
                            Product.is_active.is_(True),
                        )
                        .one_or_none()
                    )
                    if variant is not None:
                        stock = self._get_stock_count(store_id, variant.id)
                        if stock is None or stock <= 0:
                            return ResolutionResult(
                                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                                resolved_entities={},
                                context_updates={},
                                response_hint=text(
                                    (
                                        "الخيار غير متوفر حاليًا."
                                        if stock == 0
                                        else "الخيار موجود، يجب التحقق من المخزون قبل تأكيد اختياره."
                                    ),
                                    (
                                        "L’option est actuellement indisponible."
                                        if stock == 0
                                        else "L’option existe, mais son stock doit être vérifié avant de confirmer ce choix."
                                    ),
                                ),
                            )
                        return ResolutionResult(
                            allowed_action=AllowedAction.RESOLVE_VARIANT.value,
                            resolved_entities={
                                "product_id": str(product_uuid),
                                "variant_id": str(variant.id),
                                "price": float(
                                    self._get_price_for_variant(store_id, variant)
                                ),
                                "stock": stock,
                            },
                            context_updates=base_context,
                            response_hint=text(
                                "هذا الخيار متاح للاستفسار، ولم أغيّر مسودة طلبك.",
                                "Je vérifie cette option sans modifier votre commande provisoire.",
                            ),
                        )

            if (
                intent == "order_confirm" or confirmation_phrase
            ) and state.get("last_question_type") == "ORDER_CONFIRMATION":
                return ResolutionResult(
                    allowed_action=AllowedAction.CONFIRM_ORDER.value,
                    resolved_entities={},
                    context_updates={**base_context, "commerce_stage": CommerceStage.ORDER_CONFIRMED.value},
                    response_hint=text(
                        "سأؤكد طلبك الآن.",
                        "Je confirme votre commande.",
                    ),
                )

            # Handle ambiguous confirmation ("ايه", "نعم", etc.) when there's a pending question
            if confirmation_phrase and state.get("last_question_type"):
                last_q = state.get("last_question_type")
                if last_q == "PRODUCT_DETAILS_OFFER":
                    # Customer said yes to seeing product details
                    return ResolutionResult(
                        allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                        resolved_entities={"product_id": prod_id_str} if prod_id_str else {},
                        context_updates=base_context,
                        response_hint=text(
                            "سأعرض لك التفاصيل والخيارات.",
                            "Voici les détails et les options.",
                        ),
                    )
                elif last_q == "VARIANT_SELECTION":
                    # Customer said yes to variant selection - need them to specify which
                    return ResolutionResult(
                        allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                        resolved_entities={},
                        context_updates=base_context,
                        response_hint=text(
                            "أي خيار تقصد؟ حدد الرقم أو اللون/المقاس من فضلك.",
                            "Quelle option voulez-vous ? Précisez le numéro ou la couleur/la taille.",
                        ),
                    )
                elif last_q == "ORDER_CREATE_OFFER":
                    # Customer said yes to creating an order
                    if var_id_str:
                        return self._prepare_draft_creation(store_id, prod_id_str, var_id_str, quantity, base_context)
                    else:
                        return ResolutionResult(
                            allowed_action=AllowedAction.GET_PRODUCT_DETAILS.value,
                            resolved_entities={"product_id": prod_id_str} if prod_id_str else {},
                            context_updates=base_context,
                            response_hint=text(
                                "باش نبداو للطلب، نحتاج تختار الخيار أولاً.",
                                "Pour commencer la commande, il faut d'abord choisir l'option.",
                            ),
                        )

            elif intent == "order_create":
                 return ResolutionResult(
                    allowed_action=AllowedAction.UPDATE_DRAFT.value,
                    resolved_entities={},
                    context_updates=base_context,
                    response_hint=text(
                        "توجد مسودة للطلب. سأحدّث عناصرها.",
                        "Une commande provisoire existe déjà. Je vais la mettre à jour.",
                    ),
                )
            
            return self._default_result(base_context)

        if stage == CommerceStage.ORDER_CONFIRMED:
            return ResolutionResult(
                allowed_action=AllowedAction.INFO_ALREADY_CONFIRMED.value,
                resolved_entities={},
                context_updates=base_context,
                response_hint=text(
                    "تم تأكيد طلبك. شكرًا لك!",
                    "Votre commande est déjà confirmée. Merci !",
                ),
            )

        return self._default_result(base_context)

    # --- Helper Methods ---

    def _resolve_variant_availability(
        self,
        *,
        store_id: uuid.UUID,
        state: dict[str, Any],
        attributes: dict[str, Any],
        language: str,
    ) -> ResolutionResult:
        product_uuid = self._parse_uuid(state.get("selected_product_id"))
        if product_uuid is None:
            product = self._get_draft_product(store_id, state)
            product_uuid = product.id if product is not None else None

        def text(arabic: str, french: str, english: str) -> str:
            if language == "fr":
                return french
            if language == "en":
                return english
            return arabic

        if product_uuid is None or not attributes:
            return ResolutionResult(
                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                context_updates={},
                response_hint=text(
                    "لم أتمكن من التحقق من الخيار المطلوب من بيانات المنتج.",
                    "Je n’ai pas pu vérifier l’option demandée à partir des données du produit.",
                    "I could not verify the requested option from the product data.",
                ),
            )

        product = (
            self.db.query(Product)
            .filter(
                Product.id == product_uuid,
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .one_or_none()
        )
        if product is None:
            return ResolutionResult(
                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                context_updates={},
                response_hint=text(
                    "لم أتمكن من التحقق من المنتج الحالي.",
                    "Je n’ai pas pu vérifier le produit actuel.",
                    "I could not verify the current product.",
                ),
            )

        variants = (
            self.db.query(ProductVariant)
            .filter(ProductVariant.product_id == product_uuid)
            .order_by(ProductVariant.created_at.asc(), ProductVariant.id.asc())
            .all()
        )
        requested = normalize_attributes(attributes)
        matches: list[tuple[ProductVariant, int | None]] = []
        listed: list[str] = []
        for variant in variants:
            raw_attributes = variant.attributes_json
            if isinstance(raw_attributes, dict) and raw_attributes:
                normalized_attributes = normalize_attributes(raw_attributes)
                matches_request = all(
                    normalized_attributes.get(key) == value
                    for key, value in requested.items()
                )
            else:
                matches_request = self._variant_name_matches_attributes(
                    variant.name or "",
                    requested,
                )
            stock = self._get_stock_count(store_id, variant.id)
            if stock is not None and stock > 0:
                listed.append(variant.name)
            elif stock is None:
                listed.append(f"{variant.name} (المخزون غير محدد)")
            if matches_request:
                matches.append((variant, stock))

        if matches:
            variant, stock = matches[0]
            price = self._get_price_for_variant(store_id, variant)
            formatted_price = format(price.normalize(), "f")
            if stock is not None and stock > 0:
                response = text(
                    f"نعم، الخيار متوفر: {variant.name}، السعر {formatted_price} دج، والمتوفر {stock}.",
                    f"Oui, l’option est disponible : {variant.name}, prix {formatted_price} DZD, stock {stock}.",
                    f"Yes, this option is available: {variant.name}, price {formatted_price} DZD, {stock} in stock.",
                )
            elif stock == 0:
                response = text(
                    f"الخيار {variant.name} موجود، لكنه غير متوفر حاليًا.",
                    f"L’option {variant.name} existe, mais elle est actuellement indisponible.",
                    f"The {variant.name} option exists, but it is currently unavailable.",
                )
            else:
                response = text(
                    f"الخيار {variant.name} مسجل، لكن مخزونه غير موثق.",
                    f"L’option {variant.name} est répertoriée, mais son stock n’est pas vérifié.",
                    f"The {variant.name} option is listed, but its stock is unverified.",
                )
        else:
            options = "، ".join(listed) if listed else "لا توجد خيارات موثقة"
            response = text(
                f"لا أجد خيارًا موثقًا بهذه المواصفات. الخيارات المتاحة المسجلة: {options}.",
                f"Je ne trouve pas d’option vérifiée correspondant à ces caractéristiques. Options répertoriées : {', '.join(listed) if listed else 'aucune'}.",
                f"I can’t verify an option with those attributes. Listed available options: {', '.join(listed) if listed else 'none'}.",
            )

        return ResolutionResult(
            allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
            resolved_entities={
                "product_id": str(product_uuid),
                "matching_variant_id": str(matches[0][0].id) if matches else None,
            },
            context_updates={},
            response_hint=response,
        )

    def _match_candidate_products(
        self,
        store_id: uuid.UUID,
        candidate_ids: list[Any],
        product_mention: Any,
    ) -> list[Product]:
        if not isinstance(product_mention, str) or len(product_mention.strip()) < 2:
            return []

        valid_ids = []
        for candidate_id in candidate_ids:
            try:
                valid_ids.append(uuid.UUID(str(candidate_id)))
            except (ValueError, TypeError, AttributeError):
                continue
        if not valid_ids:
            return []

        mention = product_mention.strip().casefold()
        products = (
            self.db.query(Product)
            .filter(
                Product.store_id == store_id,
                Product.id.in_(valid_ids),
                Product.is_active.is_(True),
            )
            .all()
        )
        return [
            product
            for product in products
            if mention in product.name.casefold()
            or product.name.casefold() in mention
        ]

    def _get_draft_product(
        self,
        store_id: uuid.UUID,
        state: dict[str, Any],
    ) -> Product | None:
        draft = state.get("active_draft_json")
        items = draft.get("items") if isinstance(draft, dict) else None
        if not isinstance(items, list) or not items:
            return None
        first_item = items[0]
        variant_id = self._parse_uuid(
            first_item.get("variant_id") if isinstance(first_item, dict) else None
        )
        if variant_id is None:
            return None
        return (
            self.db.query(Product)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .filter(
                ProductVariant.id == variant_id,
                Product.store_id == store_id,
                Product.is_active.is_(True),
            )
            .one_or_none()
        )

    def _get_current_stage_from_db(self, state: dict) -> CommerceStage:
        """Determines stage strictly based on presence of data in state."""
        # Check Draft First (Highest Priority)
        draft = state.get("active_draft_json")
        if draft and isinstance(draft, dict) and draft.get("items"):
            return CommerceStage.DRAFT_PENDING

        if state.get("has_confirmed_order"):
            return CommerceStage.ORDER_CONFIRMED
        
        # Check Variant Selection
        if state.get("selected_variant_id"):
            return CommerceStage.VARIANT_SELECTED
            
        # Check Product Candidates (Multiple results found but none selected)
        if state.get("candidate_product_ids") and not state.get("selected_product_id"):
             return CommerceStage.PRODUCT_CANDIDATES

        # Check Product Selection
        if state.get("selected_product_id"):
            return CommerceStage.PRODUCT_SELECTED
            
        return CommerceStage.EMPTY

    def _prepare_draft_creation(
        self, 
        store_id: uuid.UUID, 
        prod_id_str: Optional[str], 
        var_id_str: Optional[str], 
        qty: int, 
        base_context: dict
    ) -> ResolutionResult:
        """Validates entities and prepares result for Draft Service."""
        if not prod_id_str or not var_id_str:
             return self._error_result(base_context, "Missing product or variant ID.")
        
        try:
            product_uuid = uuid.UUID(prod_id_str)
            var_uuid = uuid.UUID(var_id_str)
        except (ValueError, TypeError, AttributeError):
             return self._error_result(base_context, "Invalid Variant ID format.")

        # Final Safety Check: Does this variant belong to this store?
        variant = self.db.query(ProductVariant).join(Product).filter(
            ProductVariant.id == var_uuid,
            ProductVariant.product_id == product_uuid,
            Product.store_id == store_id,
            Product.is_active.is_(True),
        ).first()

        if not variant:
            return self._error_result(base_context, "Selected item is no longer available.")

        price = self._get_price_for_variant(store_id, variant)
        stock = self._get_stock_count(store_id, variant.id)

        if stock is None:
            return ResolutionResult(
                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                resolved_entities={},
                context_updates=base_context,
                response_hint=(
                    "Le stock de cette option n’est pas renseigné et doit être vérifié."
                    if base_context.get("last_nlu", {}).get("language") == "fr"
                    else "مخزون هذا الخيار غير مسجل ويجب التحقق من توفره."
                ),
            )

        if stock < qty:
            return ResolutionResult(
                allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
                resolved_entities={},
                context_updates=base_context,
                response_hint=(
                    f"Il ne reste que {stock} unité(s) disponible(s)."
                    if base_context.get("last_nlu", {}).get("language") == "fr"
                    else f"الكمية غير متوفرة بالكامل. المتبقي هو {stock}."
                ),
            )

        return ResolutionResult(
            allowed_action=AllowedAction.CREATE_DRAFT.value,
            resolved_entities={
                "product_id": str(variant.product_id),
                "variant_id": str(variant.id),
                "quantity": qty,
                "unit_price": float(price),
                "total_price": float(price * qty)
            },
            context_updates={
                **base_context,
                "commerce_stage": CommerceStage.DRAFT_PENDING.value
            },
            response_hint=(
                "Préparation de votre commande."
                if base_context.get("last_nlu", {}).get("language") == "fr"
                else "جارٍ إعداد مسودة الطلب."
            ),
        )

    def _resolve_variant_from_attributes(
        self, 
        store_id: uuid.UUID, 
        product_id: uuid.UUID, 
        attributes: dict
    ) -> Optional[ProductVariant]:
        """Matches requested attributes against DB variants."""
        variants = self.db.query(ProductVariant).join(Product).filter(
            ProductVariant.product_id == product_id,
            Product.store_id == store_id,
            Product.is_active == True
        ).all()

        if not variants:
            return None

        if not attributes:
            return variants[0] # Default to first if no specs given

        requested_attributes = normalize_attributes(attributes)

        for v in variants:
            v_attrs = getattr(v, "attributes_json", None)
            if isinstance(v_attrs, dict) and v_attrs:
                normalized_variant_attributes = normalize_attributes(v_attrs)
                match = all(
                    key in normalized_variant_attributes
                    and normalized_variant_attributes[key] == value
                    for key, value in requested_attributes.items()
                )
            else:
                match = self._variant_name_matches_attributes(
                    v.name or "",
                    requested_attributes,
                )

            if match:
                return v
        
        return None

    @staticmethod
    def _parse_uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _variant_name_matches_attributes(name: str, attributes: dict[str, Any]) -> bool:
        """Match normalized requested values against legacy variant-name text."""
        name_tokens = re.findall(r"\w+", name.casefold())
        for key, value in attributes.items():
            expected = CommerceResolver._normalize_legacy_name_value(str(value), key)
            value_tokens = re.findall(r"\w+", expected.casefold())
            if not value_tokens:
                return False

            matched = False
            max_window = min(4, len(name_tokens))
            for window_size in range(1, max_window + 1):
                for start in range(len(name_tokens) - window_size + 1):
                    candidate = " ".join(name_tokens[start:start + window_size])
                    if CommerceResolver._normalize_legacy_name_value(candidate, key) == expected:
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                return False

        return True

    @staticmethod
    def _normalize_legacy_name_value(value: str, key: str) -> str:
        normalized = normalize_value(value, key)
        if key == "color":
            return _LEGACY_COLOR_ALIASES.get(normalized, normalized)
        return normalized

    def _get_price_for_variant(self, store_id: uuid.UUID, variant: ProductVariant) -> Decimal:
        base = getattr(variant.product, 'base_price', 0)
        adj = getattr(variant, 'price_adjustment', 0)
        return Decimal(str(base)) + Decimal(str(adj))

    def _get_stock_count(
        self,
        store_id: uuid.UUID,
        variant_id: uuid.UUID,
    ) -> int | None:
        inv = self.db.query(InventoryItem).filter(
            InventoryItem.variant_id == variant_id,
            InventoryItem.store_id == store_id
        ).first()
        return inv.quantity if inv else None

    def _error_result(self, ctx: dict, msg: str) -> ResolutionResult:
        language = (ctx.get("last_nlu") or {}).get("language", "ar")
        if language == "fr":
            french_messages = {
                "No product selected.": "Aucun produit n’est sélectionné.",
                "Invalid product ID format.": "Le produit sélectionné est invalide.",
                "No variant selected.": "Aucune option n’est sélectionnée.",
                "Missing product or variant ID.": "Le produit ou son option n’a pas été identifié.",
                "Invalid Variant ID format.": "L’option sélectionnée est invalide.",
                "Selected item is no longer available.": "Cet article n’est plus disponible.",
                "لا يمكن تأكيد الطلب قبل إنشاء مسودة. قل «ديرلي طلب» أولًا.": "Créez d’abord une commande provisoire avant de la confirmer.",
            }
            response = french_messages.get(
                msg,
                "Je ne peux pas traiter cette demande pour le moment.",
            )
        elif re.search(r"[\u0600-\u06ff]", msg):
            response = msg
        else:
            arabic_messages = {
                "No product selected.": "لم يتم تحديد المنتج.",
                "Invalid product ID format.": "تعذر تحديد المنتج بشكل صحيح.",
                "No variant selected.": "يرجى اختيار أحد الخيارات أولًا.",
                "Missing product or variant ID.": "لم يتم تحديد المنتج أو الخيار المطلوب.",
                "Invalid Variant ID format.": "تعذر تحديد الخيار بشكل صحيح.",
                "Selected item is no longer available.": "هذا المنتج لم يعد متاحًا.",
            }
            response = arabic_messages.get(
                msg,
                "تعذر تنفيذ الطلب بهذه الاختيارات.",
            )
        return ResolutionResult(
            allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
            resolved_entities={},
            context_updates=ctx,
            response_hint=response,
        )

    def _default_result(self, ctx: dict) -> ResolutionResult:
        language = (ctx.get("last_nlu") or {}).get("language", "ar")
        return ResolutionResult(
            allowed_action=AllowedAction.ASK_FOR_CLARIFICATION.value,
            resolved_entities={},
            context_updates=ctx,
            response_hint=(
                "Je n’ai pas bien compris votre demande. Pouvez-vous préciser ?"
                if language == "fr"
                else "لم أفهم طلبك تمامًا. هل يمكنك توضيحه لي؟"
            ),
        )
