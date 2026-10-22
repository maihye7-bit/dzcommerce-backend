"""
Tests for the inventory endpoints (GET/PATCH), independent of product
creation. test_products.py already covers that creating a product sets
up its initial inventory correctly; this file covers reading/updating
variant stock afterwards, validation, and tenant isolation.
"""
import uuid

from app.models.product import ProductVariant
from tests.helpers import register_and_get_token, auth_headers, get_first_store_id


def _create_product(client, token, store_id, **overrides):
    payload = {
        "name": "Casquette",
        "sku": "CASQ-01",
        "price": "800.00",
        "initial_quantity": 5,
    }
    payload.update(overrides)
    return client.post(
        f"/api/stores/{store_id}/products",
        json=payload,
        headers=auth_headers(token),
    )


def _variant_id(db_session, product_id):
    return (
        db_session.query(ProductVariant.id)
        .filter(ProductVariant.product_id == uuid.UUID(str(product_id)))
        .scalar()
    )


def _inventory_url(store_id, variant_id):
    return f"/api/stores/{store_id}/variants/{variant_id}/inventory"


def test_get_inventory_returns_current_quantity(client, db_session):
    token = register_and_get_token(client, "inv1@example.com", store_name="Store Inv1")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id, initial_quantity=17).json()
    variant_id = _variant_id(db_session, product["id"])

    resp = client.get(
        _inventory_url(store_id, variant_id),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 17
    assert body["variant_id"] == str(variant_id)
    assert body["store_id"] == store_id


def test_list_store_inventory_returns_product_variants_and_stock(client):
    token = register_and_get_token(
        client, "inv-list@example.com", store_name="Store Inventory List"
    )
    store_id = get_first_store_id(client, token)
    product = _create_product(
        client, token, store_id, name="Inventory list item", initial_quantity=17
    ).json()

    response = client.get(
        f"/api/stores/{store_id}/inventory/products",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == product["id"]
    assert items[0]["name"] == "Inventory list item"
    assert items[0]["base_price"] == 800.0
    assert len(items[0]["variants"]) == 1
    assert items[0]["variants"][0]["name"] == "Standard"
    assert items[0]["variants"][0]["quantity"] == 17
    assert items[0]["variants"][0]["inventory_id"] is not None


def test_list_store_inventory_rejects_unauthenticated_and_other_store(client):
    owner_token = register_and_get_token(
        client, "inv-list-owner@example.com", store_name="Inventory List Owner"
    )
    store_id = get_first_store_id(client, owner_token)
    other_token = register_and_get_token(
        client, "inv-list-other@example.com", store_name="Inventory List Other"
    )

    assert client.get(f"/api/stores/{store_id}/inventory/products").status_code == 401
    response = client.get(
        f"/api/stores/{store_id}/inventory/products",
        headers=auth_headers(other_token),
    )
    assert response.status_code == 404


def test_update_inventory_quantity(client, db_session):
    token = register_and_get_token(client, "inv2@example.com", store_name="Store Inv2")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id, initial_quantity=5).json()
    variant_id = _variant_id(db_session, product["id"])

    resp = client.patch(
        _inventory_url(store_id, variant_id),
        json={"quantity": 42},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 42

    # Confirm it actually persisted, via a fresh GET.
    check = client.get(
        _inventory_url(store_id, variant_id),
        headers=auth_headers(token),
    )
    assert check.json()["quantity"] == 42


def test_get_inventory_for_nonexistent_variant_404(client):
    token = register_and_get_token(client, "inv3@example.com", store_name="Store Inv3")
    store_id = get_first_store_id(client, token)

    resp = client.get(
        _inventory_url(store_id, "00000000-0000-0000-0000-000000000000"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_negative_inventory_quantity_rejected(client, db_session):
    token = register_and_get_token(client, "inv4@example.com", store_name="Store Inv4")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()
    variant_id = _variant_id(db_session, product["id"])

    resp = client.patch(
        _inventory_url(store_id, variant_id),
        json={"quantity": -1},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422

    # Confirm the rejected update did not silently apply.
    check = client.get(
        _inventory_url(store_id, variant_id),
        headers=auth_headers(token),
    )
    assert check.json()["quantity"] == 5


def test_negative_initial_quantity_rejected_at_product_creation(client):
    token = register_and_get_token(client, "inv5@example.com", store_name="Store Inv5")
    store_id = get_first_store_id(client, token)

    resp = _create_product(client, token, store_id, initial_quantity=-3)
    assert resp.status_code == 422


def test_user_cannot_read_inventory_of_another_store(client, db_session):
    token_a = register_and_get_token(client, "inv6a@example.com", store_name="Store Inv6A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()
    variant_id = _variant_id(db_session, product["id"])

    token_b = register_and_get_token(client, "inv6b@example.com", store_name="Store Inv6B")

    resp = client.get(
        _inventory_url(store_a, variant_id),
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404


def test_user_cannot_update_inventory_of_another_store(client, db_session):
    token_a = register_and_get_token(client, "inv7a@example.com", store_name="Store Inv7A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()
    variant_id = _variant_id(db_session, product["id"])

    token_b = register_and_get_token(client, "inv7b@example.com", store_name="Store Inv7B")

    resp = client.patch(
        _inventory_url(store_a, variant_id),
        json={"quantity": 999},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404

    # Confirm the owner's inventory was untouched by the intruder's attempt.
    check = client.get(
        _inventory_url(store_a, variant_id),
        headers=auth_headers(token_a),
    )
    assert check.json()["quantity"] == 5


def test_inventory_not_found_when_variant_belongs_to_different_store(client, db_session):
    """
    The membership check for store_a passes (token_a really does belong
    to store_a), but product_id refers to a product actually owned by
    store_b. This must still 404 -- the service layer's own
    Product.store_id == store_id filter is what catches this, not the
    membership dependency alone.
    """
    token_a = register_and_get_token(client, "inv8a@example.com", store_name="Store Inv8A")
    store_a = get_first_store_id(client, token_a)

    token_b = register_and_get_token(client, "inv8b@example.com", store_name="Store Inv8B")
    store_b = get_first_store_id(client, token_b)
    product_b = _create_product(client, token_b, store_b).json()
    variant_id = _variant_id(db_session, product_b["id"])

    resp = client.get(
        _inventory_url(store_a, variant_id),
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 404
