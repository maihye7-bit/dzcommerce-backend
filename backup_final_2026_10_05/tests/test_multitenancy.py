def _register(client, email, password="supersecret1", store_name="Store"):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "store_name": store_name,
        },
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_new_owner_sees_only_their_store(client):
    token = _register(client, "owner1@example.com", store_name="Store One")
    resp = client.get("/api/stores", headers=_auth_headers(token))
    assert resp.status_code == 200
    stores = resp.json()
    assert len(stores) == 1
    assert stores[0]["name"] == "Store One"
    assert stores[0]["role"] == "owner"


def test_user_cannot_see_other_merchants_store(client):
    token_a = _register(client, "merchant_a@example.com", store_name="Store A")
    _register(client, "merchant_b@example.com", store_name="Store B")

    # merchant A lists their stores: should never include Store B
    resp = client.get("/api/stores", headers=_auth_headers(token_a))
    names = [s["name"] for s in resp.json()]
    assert names == ["Store A"]


def test_user_cannot_fetch_store_they_do_not_belong_to(client):
    token_a = _register(client, "merchant_c@example.com", store_name="Store C")
    token_b = _register(client, "merchant_d@example.com", store_name="Store D")

    store_b_id = client.get("/api/stores", headers=_auth_headers(token_b)).json()[0]["id"]

    # merchant A tries to access merchant B's store directly by id
    resp = client.get(f"/api/stores/{store_b_id}", headers=_auth_headers(token_a))
    assert resp.status_code == 404  # not 403, to avoid leaking existence


def test_user_can_fetch_their_own_store(client):
    token = _register(client, "merchant_e@example.com", store_name="Store E")
    store_id = client.get("/api/stores", headers=_auth_headers(token)).json()[0]["id"]

    resp = client.get(f"/api/stores/{store_id}", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Store E"


def test_two_stores_with_same_name_get_different_slugs(client):
    _register(client, "dup1@example.com", store_name="Same Name")
    _register(client, "dup2@example.com", store_name="Same Name")

    # Both registrations succeeded (no crash on slug collision) -- verified implicitly
    # by absence of an exception/500. Explicitly check via login + store fetch.
    token1 = client.post(
        "/api/auth/login", data={"username": "dup1@example.com", "password": "supersecret1"}
    ).json()["access_token"]
    token2 = client.post(
        "/api/auth/login", data={"username": "dup2@example.com", "password": "supersecret1"}
    ).json()["access_token"]

    slug1 = client.get("/api/stores", headers=_auth_headers(token1)).json()[0]["slug"]
    slug2 = client.get("/api/stores", headers=_auth_headers(token2)).json()[0]["slug"]
    assert slug1 != slug2
