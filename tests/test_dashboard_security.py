import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.product import ProductVariant
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from tests.helpers import auth_headers, get_first_store_id, register_and_get_token


def _seed_customer_order_conversation(db_session, store_id):
    customer = Customer(store_id=store_id, name="Dashboard customer")
    db_session.add(customer)
    db_session.flush()
    order = Order(
        store_id=store_id,
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("100"),
        total=Decimal("100"),
    )
    conversation = Conversation(
        store_id=store_id,
        customer_id=customer.id,
        channel="api",
        status="active",
    )
    db_session.add_all([order, conversation])
    db_session.flush()
    db_session.add(
        Message(
            conversation_id=conversation.id,
            role="customer",
            content="Order update",
        )
    )
    db_session.commit()
    return order, conversation


def _create_staff(db_session, store_id, suffix):
    user = User(
        email=f"staff-{suffix}@example.com",
        hashed_password=hash_password("staff-password-1"),
        full_name="Store Staff",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        StoreUser(store_id=store_id, user_id=user.id, role=StoreRole.STAFF)
    )
    db_session.commit()
    return create_access_token(str(user.id))


def test_all_order_conversation_dashboard_and_stats_routes_require_auth(client):
    other_id = uuid.uuid4()
    routes = [
        f"/api/dashboard/stats?store_id={other_id}",
        f"/api/dashboard/orders?store_id={other_id}",
        f"/api/dashboard/conversations?store_id={other_id}",
        "/api/orders/",
        "/api/conversations/",
        f"/api/conversations/{other_id}/messages",
        f"/api/stats/dashboard?store_id={other_id}",
    ]

    for route in routes:
        assert client.get(route).status_code == 401, route


def test_dashboard_store_selection_is_validated_against_membership(client):
    token = register_and_get_token(
        client, "dashboard-a@example.com", store_name="Dashboard Store A"
    )
    other_token = register_and_get_token(
        client, "dashboard-b@example.com", store_name="Dashboard Store B"
    )
    other_store_id = get_first_store_id(client, other_token)

    for endpoint in ("stats", "orders", "conversations"):
        response = client.get(
            f"/api/dashboard/{endpoint}?store_id={other_store_id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 404


def test_orders_route_only_returns_orders_from_user_memberships(
    client, db_session
):
    token_a = register_and_get_token(
        client, "orders-a@example.com", store_name="Orders Store A"
    )
    token_b = register_and_get_token(
        client, "orders-b@example.com", store_name="Orders Store B"
    )
    store_a = get_first_store_id(client, token_a)
    store_b = get_first_store_id(client, token_b)
    order_a, _ = _seed_customer_order_conversation(db_session, uuid.UUID(store_a))
    order_b, _ = _seed_customer_order_conversation(db_session, uuid.UUID(store_b))

    response = client.get("/api/orders/", headers=auth_headers(token_a))

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert str(order_a.id) in returned_ids
    assert str(order_b.id) not in returned_ids


def test_conversation_transcript_rejects_cross_store_access(client, db_session):
    token_a = register_and_get_token(
        client, "transcript-a@example.com", store_name="Transcript Store A"
    )
    token_b = register_and_get_token(
        client, "transcript-b@example.com", store_name="Transcript Store B"
    )
    store_a = uuid.UUID(get_first_store_id(client, token_a))
    store_b = uuid.UUID(get_first_store_id(client, token_b))
    _, conversation_a = _seed_customer_order_conversation(db_session, store_a)
    _, conversation_b = _seed_customer_order_conversation(db_session, store_b)

    own_response = client.get(
        f"/api/conversations/{conversation_a.id}/messages",
        headers=auth_headers(token_a),
    )
    other_response = client.get(
        f"/api/conversations/{conversation_b.id}/messages",
        headers=auth_headers(token_a),
    )

    assert own_response.status_code == 200
    assert len(own_response.json()) == 1
    assert other_response.status_code == 404


def test_staff_can_read_but_cannot_write_store_resources(client, db_session):
    owner_token = register_and_get_token(
        client, "staff-owner@example.com", store_name="Staff Access Store"
    )
    store_id = uuid.UUID(get_first_store_id(client, owner_token))
    product_response = client.post(
        f"/api/stores/{store_id}/products",
        json={"name": "Owner product", "price": "10.00", "initial_quantity": 4},
        headers=auth_headers(owner_token),
    )
    assert product_response.status_code == 201
    product_id = uuid.UUID(product_response.json()["id"])
    variant_id = (
        db_session.query(ProductVariant.id)
        .filter(ProductVariant.product_id == product_id)
        .scalar()
    )
    staff_token = _create_staff(db_session, store_id, "read-write")

    products_response = client.get(
        f"/api/stores/{store_id}/products",
        headers=auth_headers(staff_token),
    )
    inventory_response = client.get(
        f"/api/stores/{store_id}/variants/{variant_id}/inventory",
        headers=auth_headers(staff_token),
    )
    create_response = client.post(
        f"/api/stores/{store_id}/products",
        json={"name": "Staff product", "price": "10.00"},
        headers=auth_headers(staff_token),
    )
    product_update_response = client.patch(
        f"/api/stores/{store_id}/products/{product_id}",
        json={"name": "Unauthorized update"},
        headers=auth_headers(staff_token),
    )
    product_delete_response = client.delete(
        f"/api/stores/{store_id}/products/{product_id}",
        headers=auth_headers(staff_token),
    )
    inventory_update_response = client.patch(
        f"/api/stores/{store_id}/variants/{variant_id}/inventory",
        json={"quantity": 99},
        headers=auth_headers(staff_token),
    )
    store_update_response = client.patch(
        f"/api/stores/{store_id}",
        json={"name": "Unauthorized rename"},
        headers=auth_headers(staff_token),
    )

    assert products_response.status_code == 200
    assert inventory_response.status_code == 200
    assert create_response.status_code == 403
    assert product_update_response.status_code == 403
    assert product_delete_response.status_code == 403
    assert inventory_update_response.status_code == 403
    assert store_update_response.status_code == 403


def test_owner_can_update_store_profile(client):
    token = register_and_get_token(
        client, "store-owner-update@example.com", store_name="Original Shop"
    )
    store_id = get_first_store_id(client, token)

    response = client.patch(
        f"/api/stores/{store_id}",
        json={"name": "Updated Shop"},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Shop"


def test_login_rate_limit_is_five_attempts_per_minute(client):
    email = "login-rate-limit@example.com"
    register_and_get_token(client, email, store_name="Login Rate Limit")

    responses = [
        client.post(
            "/api/auth/login",
            data={"username": email, "password": "wrong-password"},
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses] == [
        401,
        401,
        401,
        401,
        401,
        429,
    ]
    assert responses[-1].headers["Retry-After"] == "60"


def test_registration_rate_limit_is_five_attempts_per_minute(client):
    email = "registration-rate-limit@example.com"
    payload = {
        "email": email,
        "password": "long-password-1",
        "full_name": "Rate Limit",
        "store_name": "Rate Limit Store",
    }

    responses = [
        client.post("/api/auth/register", json=payload)
        for _ in range(6)
    ]

    assert [response.status_code for response in responses] == [
        201,
        400,
        400,
        400,
        400,
        429,
    ]
