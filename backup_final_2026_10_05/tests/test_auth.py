def _register(client, email="merchant@example.com", password="supersecret1", store_name="Boutique Alger"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Karim Merchant",
            "store_name": store_name,
        },
    )


def test_register_creates_user_and_returns_token(client):
    resp = _register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_register_duplicate_email_rejected(client):
    _register(client)
    resp = _register(client)
    assert resp.status_code == 400


def test_login_with_correct_credentials(client):
    _register(client, email="a@example.com", password="mypassword1")
    resp = client.post(
        "/api/auth/login",
        data={"username": "a@example.com", "password": "mypassword1"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_with_wrong_password_rejected(client):
    _register(client, email="b@example.com", password="correctpass1")
    resp = client.post(
        "/api/auth/login",
        data={"username": "b@example.com", "password": "wrongpass1"},
    )
    assert resp.status_code == 401


def test_login_unknown_email_rejected(client):
    resp = client.post(
        "/api/auth/login",
        data={"username": "nobody@example.com", "password": "whatever1"},
    )
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client):
    token = _register(client, email="c@example.com").json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "c@example.com"


def test_me_rejects_invalid_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
