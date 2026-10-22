"""
Small shared helpers for tests that need an authenticated user with a
store already set up (products and inventory tests). Kept separate from
conftest.py fixtures so Phase 1's existing test files stay untouched.
"""


def register_and_get_token(client, email, password="supersecret1", store_name="Store"):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "store_name": store_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_first_store_id(client, token):
    resp = client.get("/api/stores", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]
