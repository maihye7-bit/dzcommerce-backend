import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app.agent.commerce_resolver import AllowedAction, CommerceResolver, ResolutionResult
from app.models.inventory import InventoryItem
from app.models.product import ProductVariant


def _variant(name: str, attributes: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        name=name,
        attributes_json=attributes,
        price_adjustment=Decimal("0"),
        product=SimpleNamespace(base_price=Decimal("45000")),
    )


def _resolve(
    variants: list[SimpleNamespace],
    attributes: dict,
) -> ResolutionResult:
    db = Mock()
    variant_query = Mock()
    variant_query.join.return_value.filter.return_value.all.return_value = variants
    inventory_query = Mock()
    inventory_query.filter.return_value.first.return_value = SimpleNamespace(quantity=8)

    def query_for(model):
        if model is ProductVariant:
            return variant_query
        if model is InventoryItem:
            return inventory_query
        raise AssertionError(f"Unexpected model queried: {model}")

    db.query.side_effect = query_for
    product_id = variants[0].product_id
    store_id = uuid.uuid4()
    state = {
        "selected_product_id": str(product_id),
        "active_draft_json": {},
    }
    result = CommerceResolver(db).resolve(
        nlu_output={
            "intent": "variant_selection",
            "attributes": attributes,
        },
        current_state=state,
        store_id=store_id,
    )
    return result


def test_matches_normalized_electronics_attributes() -> None:
    wrong_variant = _variant(
        "128GB / Gray",
        {"storage": "128gb", "color": "gray"},
    )
    expected_variant = _variant(
        "Samsung Galaxy A54",
        {"storage": "256GB", "color": "black"},
    )
    result = _resolve(
        [wrong_variant, expected_variant],
        {"التخزين": "256 غيغا", "اللون": "أسود"},
    )

    assert result.allowed_action == "CALL_SERVICE:resolve_variant"
    assert result.resolved_entities["variant_id"] == str(expected_variant.id)
    assert result.context_updates["selected_variant_id"] == str(expected_variant.id)


def test_matches_normalized_furniture_material() -> None:
    expected_variant = _variant(
        "Oak dining table",
        {"material": "wood"},
    )
    result = _resolve([expected_variant], {"مادة": "خشب"})

    assert result.allowed_action == AllowedAction.RESOLVE_VARIANT.value
    assert result.resolved_entities["variant_id"] == str(expected_variant.id)


def test_legacy_variant_name_fallback_normalizes_color_and_size() -> None:
    expected_variant = _variant("Noir / 42", None)
    result = _resolve(
        [expected_variant],
        {"color": "black", "size": "42"},
    )

    assert result.allowed_action == AllowedAction.RESOLVE_VARIANT.value
    assert result.resolved_entities["variant_id"] == str(expected_variant.id)


def test_legacy_variant_name_fallback_matches_darija_color_variant() -> None:
    expected_variant = _variant("سودا / 42", None)
    result = _resolve(
        [expected_variant],
        {"color": "أسود", "size": "42"},
    )

    assert result.allowed_action == AllowedAction.RESOLVE_VARIANT.value
    assert result.resolved_entities["variant_id"] == str(expected_variant.id)


def test_unmatched_attributes_keep_product_details_fallback() -> None:
    variant = _variant("Samsung Galaxy A54", {"storage": "256gb"})
    result = _resolve([variant], {"ram": "16gb"})

    assert result.allowed_action == AllowedAction.GET_PRODUCT_DETAILS.value
    assert result.resolved_entities == {"product_id": str(variant.product_id)}
