"""
Tests for the inventory endpoints (GET/PATCH), independent of product
creation. test_products.py already covers that creating a product sets
up its initial inventory correctly; this file covers reading/updating
inventory afterwards, validation, and tenant isolation.
"""
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


def test_get_inventory_returns_current_quantity(client):
    token = register_and_get_token(client, "inv1@example.com", store_name="Store Inv1")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id, initial_quantity=17).json()

    resp = client.get(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 17
    assert body["product_id"] == product["id"]
    assert body["store_id"] == store_id


def test_update_inventory_quantity(client):
    token = register_and_get_token(client, "inv2@example.com", store_name="Store Inv2")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id, initial_quantity=5).json()

    resp = client.patch(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        json={"quantity": 42},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 42

    # Confirm it actually persisted, via a fresh GET.
    check = client.get(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        headers=auth_headers(token),
    )
    assert check.json()["quantity"] == 42


def test_get_inventory_for_nonexistent_product_404(client):
    token = register_and_get_token(client, "inv3@example.com", store_name="Store Inv3")
    store_id = get_first_store_id(client, token)

    resp = client.get(
        f"/api/stores/{store_id}/products/00000000-0000-0000-0000-000000000000/inventory",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_negative_inventory_quantity_rejected(client):
    token = register_and_get_token(client, "inv4@example.com", store_name="Store Inv4")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()

    resp = client.patch(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        json={"quantity": -1},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422

    # Confirm the rejected update did not silently apply.
    check = client.get(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        headers=auth_headers(token),
    )
    assert check.json()["quantity"] == 5


def test_negative_initial_quantity_rejected_at_product_creation(client):
    token = register_and_get_token(client, "inv5@example.com", store_name="Store Inv5")
    store_id = get_first_store_id(client, token)

    resp = _create_product(client, token, store_id, initial_quantity=-3)
    assert resp.status_code == 422


def test_user_cannot_read_inventory_of_another_store(client):
    token_a = register_and_get_token(client, "inv6a@example.com", store_name="Store Inv6A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()

    token_b = register_and_get_token(client, "inv6b@example.com", store_name="Store Inv6B")

    resp = client.get(
        f"/api/stores/{store_a}/products/{product['id']}/inventory",
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404


def test_user_cannot_update_inventory_of_another_store(client):
    token_a = register_and_get_token(client, "inv7a@example.com", store_name="Store Inv7A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()

    token_b = register_and_get_token(client, "inv7b@example.com", store_name="Store Inv7B")

    resp = client.patch(
        f"/api/stores/{store_a}/products/{product['id']}/inventory",
        json={"quantity": 999},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404

    # Confirm the owner's inventory was untouched by the intruder's attempt.
    check = client.get(
        f"/api/stores/{store_a}/products/{product['id']}/inventory",
        headers=auth_headers(token_a),
    )
    assert check.json()["quantity"] == 5


def test_inventory_not_found_when_product_id_belongs_to_different_store(client):
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

    resp = client.get(
        f"/api/stores/{store_a}/products/{product_b['id']}/inventory",
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 404
