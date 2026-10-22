"""
Tests for product endpoints: CRUD, validation rules, and tenant
isolation (a user must never touch another store's products).
"""
from decimal import Decimal

from tests.helpers import register_and_get_token, auth_headers, get_first_store_id


def _create_product(client, token, store_id, **overrides):
    payload = {
        "name": "T-Shirt Noir",
        "description": "Coton 100%",
        "sku": "TSHIRT-NOIR-M",
        "price": "1500.00",
        "initial_quantity": 10,
    }
    payload.update(overrides)
    return client.post(
        f"/api/stores/{store_id}/products",
        json=payload,
        headers=auth_headers(token),
    )


def test_create_product_success(client):
    token = register_and_get_token(client, "p1@example.com", store_name="Store P1")
    store_id = get_first_store_id(client, token)

    resp = _create_product(client, token, store_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "T-Shirt Noir"
    assert body["sku"] == "TSHIRT-NOIR-M"
    assert Decimal(body["price"]) == Decimal("1500.00")
    assert body["is_active"] is True
    assert body["store_id"] == store_id


def test_create_product_sets_initial_inventory(client):
    token = register_and_get_token(client, "p2@example.com", store_name="Store P2")
    store_id = get_first_store_id(client, token)

    product = _create_product(client, token, store_id, initial_quantity=25).json()

    resp = client.get(
        f"/api/stores/{store_id}/products/{product['id']}/inventory",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 25


def test_create_product_defaults_to_zero_inventory(client):
    token = register_and_get_token(client, "p2b@example.com", store_name="Store P2B")
    store_id = get_first_store_id(client, token)

    product = _create_product(client, token, store_id).json()
    # overrides didn't include initial_quantity here, default payload sets 10 though;
    # explicitly test the zero-default by omitting it from the payload.
    payload = {"name": "No Stock Item", "price": "500.00"}
    resp = client.post(
        f"/api/stores/{store_id}/products", json=payload, headers=auth_headers(token)
    )
    assert resp.status_code == 201
    product2 = resp.json()

    inv_resp = client.get(
        f"/api/stores/{store_id}/products/{product2['id']}/inventory",
        headers=auth_headers(token),
    )
    assert inv_resp.status_code == 200
    assert inv_resp.json()["quantity"] == 0


def test_list_products(client):
    token = register_and_get_token(client, "p3@example.com", store_name="Store P3")
    store_id = get_first_store_id(client, token)

    _create_product(client, token, store_id, sku="SKU-A", name="A")
    _create_product(client, token, store_id, sku="SKU-B", name="B")

    resp = client.get(f"/api/stores/{store_id}/products", headers=auth_headers(token))
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert names == {"A", "B"}


def test_get_single_product(client):
    token = register_and_get_token(client, "p4@example.com", store_name="Store P4")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()

    resp = client.get(
        f"/api/stores/{store_id}/products/{product['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == product["id"]


def test_get_nonexistent_product_404(client):
    token = register_and_get_token(client, "p5@example.com", store_name="Store P5")
    store_id = get_first_store_id(client, token)

    resp = client.get(
        f"/api/stores/{store_id}/products/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_update_product(client):
    token = register_and_get_token(client, "p6@example.com", store_name="Store P6")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()

    resp = client.patch(
        f"/api/stores/{store_id}/products/{product['id']}",
        json={"price": "1999.99", "name": "T-Shirt Noir V2"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "T-Shirt Noir V2"
    assert Decimal(body["price"]) == Decimal("1999.99")
    assert body["sku"] == "TSHIRT-NOIR-M"  # untouched by the partial update


def test_update_nonexistent_product_404(client):
    token = register_and_get_token(client, "p6b@example.com", store_name="Store P6B")
    store_id = get_first_store_id(client, token)

    resp = client.patch(
        f"/api/stores/{store_id}/products/00000000-0000-0000-0000-000000000000",
        json={"name": "Doesn't matter"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_delete_product_deactivates_not_removes(client):
    token = register_and_get_token(client, "p7@example.com", store_name="Store P7")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()

    resp = client.delete(
        f"/api/stores/{store_id}/products/{product['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 204

    # Still readable (soft-deleted), but marked inactive rather than gone.
    resp2 = client.get(
        f"/api/stores/{store_id}/products/{product['id']}", headers=auth_headers(token)
    )
    assert resp2.status_code == 200
    assert resp2.json()["is_active"] is False


def test_delete_nonexistent_product_404(client):
    token = register_and_get_token(client, "p7b@example.com", store_name="Store P7B")
    store_id = get_first_store_id(client, token)

    resp = client.delete(
        f"/api/stores/{store_id}/products/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_negative_price_rejected(client):
    token = register_and_get_token(client, "p8@example.com", store_name="Store P8")
    store_id = get_first_store_id(client, token)

    resp = _create_product(client, token, store_id, price="-10.00")
    assert resp.status_code == 422


def test_negative_price_rejected_on_update(client):
    token = register_and_get_token(client, "p8b@example.com", store_name="Store P8B")
    store_id = get_first_store_id(client, token)
    product = _create_product(client, token, store_id).json()

    resp = client.patch(
        f"/api/stores/{store_id}/products/{product['id']}",
        json={"price": "-5.00"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422


def test_empty_name_rejected(client):
    token = register_and_get_token(client, "p9@example.com", store_name="Store P9")
    store_id = get_first_store_id(client, token)

    resp = _create_product(client, token, store_id, name="")
    assert resp.status_code == 422


def test_duplicate_sku_within_same_store_rejected(client):
    token = register_and_get_token(client, "p10@example.com", store_name="Store P10")
    store_id = get_first_store_id(client, token)

    resp1 = _create_product(client, token, store_id, sku="DUPLICATE-SKU")
    assert resp1.status_code == 201

    resp2 = _create_product(client, token, store_id, sku="DUPLICATE-SKU", name="Other Product")
    assert resp2.status_code == 409


def test_duplicate_sku_rejected_on_update(client):
    token = register_and_get_token(client, "p10b@example.com", store_name="Store P10B")
    store_id = get_first_store_id(client, token)

    _create_product(client, token, store_id, sku="EXISTING-SKU", name="First")
    second = _create_product(client, token, store_id, sku="OTHER-SKU", name="Second").json()

    resp = client.patch(
        f"/api/stores/{store_id}/products/{second['id']}",
        json={"sku": "EXISTING-SKU"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 409


def test_same_sku_allowed_in_different_stores(client):
    token_a = register_and_get_token(client, "p11a@example.com", store_name="Store P11A")
    store_a = get_first_store_id(client, token_a)
    token_b = register_and_get_token(client, "p11b@example.com", store_name="Store P11B")
    store_b = get_first_store_id(client, token_b)

    resp_a = _create_product(client, token_a, store_a, sku="SHARED-SKU")
    resp_b = _create_product(client, token_b, store_b, sku="SHARED-SKU")

    assert resp_a.status_code == 201
    assert resp_b.status_code == 201


def test_user_cannot_list_products_of_another_store(client):
    token_a = register_and_get_token(client, "p12a@example.com", store_name="Store P12A")
    store_a = get_first_store_id(client, token_a)
    _create_product(client, token_a, store_a, sku="SECRET-A")

    token_b = register_and_get_token(client, "p12b@example.com", store_name="Store P12B")

    resp = client.get(f"/api/stores/{store_a}/products", headers=auth_headers(token_b))
    assert resp.status_code == 404  # membership check fails before reaching products


def test_user_cannot_read_single_product_of_another_store(client):
    token_a = register_and_get_token(client, "p13a@example.com", store_name="Store P13A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()

    token_b = register_and_get_token(client, "p13b@example.com", store_name="Store P13B")

    resp = client.get(
        f"/api/stores/{store_a}/products/{product['id']}", headers=auth_headers(token_b)
    )
    assert resp.status_code == 404


def test_user_cannot_create_product_in_another_store(client):
    token_a = register_and_get_token(client, "p14a@example.com", store_name="Store P14A")
    store_a = get_first_store_id(client, token_a)

    token_b = register_and_get_token(client, "p14b@example.com", store_name="Store P14B")

    resp = _create_product(client, token_b, store_a, sku="INTRUDER-SKU")
    assert resp.status_code == 404


def test_user_cannot_update_product_of_another_store(client):
    token_a = register_and_get_token(client, "p15a@example.com", store_name="Store P15A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()

    token_b = register_and_get_token(client, "p15b@example.com", store_name="Store P15B")

    resp = client.patch(
        f"/api/stores/{store_a}/products/{product['id']}",
        json={"name": "Hacked"},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 404


def test_user_cannot_delete_product_of_another_store(client):
    token_a = register_and_get_token(client, "p16a@example.com", store_name="Store P16A")
    store_a = get_first_store_id(client, token_a)
    product = _create_product(client, token_a, store_a).json()

    token_b = register_and_get_token(client, "p16b@example.com", store_name="Store P16B")

    resp = client.delete(
        f"/api/stores/{store_a}/products/{product['id']}", headers=auth_headers(token_b)
    )
    assert resp.status_code == 404

    # Confirm it's untouched from the owner's point of view.
    check = client.get(
        f"/api/stores/{store_a}/products/{product['id']}", headers=auth_headers(token_a)
    )
    assert check.json()["is_active"] is True


def test_product_not_found_when_id_belongs_to_a_different_store(client):
    """
    token_a IS a legitimate member of store_a (membership check passes),
    but product_id actually belongs to store_b. This must still 404 --
    proving isolation is enforced by the service layer's own
    Product.store_id == store_id filter, not only by the membership
    dependency at the router boundary.
    """
    token_a = register_and_get_token(client, "p17a@example.com", store_name="Store P17A")
    store_a = get_first_store_id(client, token_a)

    token_b = register_and_get_token(client, "p17b@example.com", store_name="Store P17B")
    store_b = get_first_store_id(client, token_b)
    product_b = _create_product(client, token_b, store_b, sku="CROSS-STORE").json()

    resp = client.get(
        f"/api/stores/{store_a}/products/{product_b['id']}", headers=auth_headers(token_a)
    )
    assert resp.status_code == 404
