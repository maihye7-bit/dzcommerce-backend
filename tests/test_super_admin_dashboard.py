import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from app.core.security import hash_password, verify_password
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User


def _csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login_super_admin(client, db_session, email="super-admin@example.com"):
    user = User(
        email=email,
        hashed_password=hash_password("SuperAdminPass123"),
        full_name="Platform Admin",
        is_super_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    page = client.get("/dashboard/login")
    response = client.post(
        "/dashboard/login",
        data={
            "username": email,
            "password": "SuperAdminPass123",
            "csrf_token": _csrf_from(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/super-admin"
    return client, _csrf_from(client.get("/super-admin").text), user


def test_super_admin_routes_require_super_admin_session(client):
    response = client.get("/super-admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/login"


def test_super_admin_search_filters_and_toggle_require_csrf(client, db_session):
    admin, csrf, _ = _login_super_admin(client, db_session)
    active = Store(name="North Shop", slug="north-shop", is_active=True)
    suspended = Store(name="South Shop", slug="south-shop", is_active=False)
    db_session.add_all([active, suspended])
    db_session.commit()

    all_stores = admin.get("/super-admin")
    assert "إجمالي المتاجر" in all_stores.text
    assert "North Shop" in all_stores.text
    assert "South Shop" in all_stores.text

    filtered = admin.get("/super-admin?q=north&state=active")
    assert "North Shop" in filtered.text
    assert "South Shop" not in filtered.text

    rejected = admin.post(f"/super-admin/stores/{active.id}/toggle")
    assert rejected.status_code == 403
    accepted = admin.post(
        f"/super-admin/stores/{active.id}/toggle",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    db_session.refresh(active)
    assert active.is_active is False


def test_create_store_creates_owner_in_same_store(client, db_session):
    admin, csrf, _ = _login_super_admin(client, db_session)
    response = admin.post(
        "/super-admin/stores/new",
        data={
            "name": "Fresh Shop",
            "slug": "fresh-shop",
            "owner_name": "Fresh Owner",
            "password": "OwnerPassword123!",
            "email": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = parse_qs(urlparse(response.headers["location"]).query)["notice"][0]
    assert "تم إنشاء المتجر بنجاح" in notice
    assert "owner-" in notice

    store = db_session.query(Store).filter(Store.slug == "fresh-shop").one()
    owner_link = (
        db_session.query(StoreUser)
        .filter(StoreUser.store_id == store.id, StoreUser.role == StoreRole.OWNER)
        .one()
    )
    owner = db_session.query(User).filter(User.id == owner_link.user_id).one()
    assert owner.full_name == "Fresh Owner"
    assert owner.email.endswith("@local.invalid")
    assert verify_password("OwnerPassword123!", owner.hashed_password)
    assert owner.is_super_admin is False


def test_store_detail_reports_stats_recent_orders_and_conversations(
    client, db_session
):
    admin, _, _ = _login_super_admin(client, db_session)
    store = Store(name="Detail Shop", slug="detail-shop")
    db_session.add(store)
    db_session.flush()
    product = Product(
        store_id=store.id,
        name="Item",
        base_price=Decimal("25"),
    )
    customer = Customer(store_id=store.id, name="Customer")
    db_session.add_all([product, customer])
    db_session.flush()
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("1200"),
        total=Decimal("1200"),
        created_at=datetime.now() - timedelta(days=2),
    )
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status="active",
    )
    db_session.add_all([order, conversation])
    db_session.commit()

    response = admin.get("/super-admin/stores/detail-shop")
    assert response.status_code == 200
    assert "Detail Shop" in response.text
    assert "المنتجات" in response.text
    assert "1,200" in response.text
    assert "ORD-" in response.text
    assert "فيسبوك" in response.text


def test_super_admin_can_enter_store_as_owner_and_return(client, db_session):
    admin, csrf, _ = _login_super_admin(client, db_session)
    store = Store(name="Impersonated", slug="impersonated")
    owner = User(
        email="impersonated-owner@example.com",
        hashed_password=hash_password("OwnerPassword123"),
        full_name="Store Owner",
    )
    db_session.add_all([store, owner])
    db_session.flush()
    db_session.add(
        StoreUser(store_id=store.id, user_id=owner.id, role=StoreRole.OWNER)
    )
    db_session.commit()

    entered = admin.post(
        f"/super-admin/stores/{store.id}/impersonate",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert entered.status_code == 303
    assert entered.headers["location"] == "/dashboard"
    dashboard = admin.get("/dashboard")
    assert dashboard.status_code == 200
    assert "العودة إلى إدارة المتاجر" in dashboard.text

    returned = admin.post(
        "/super-admin/stop-impersonation",
        data={"csrf_token": _csrf_from(dashboard.text)},
        follow_redirects=False,
    )
    assert returned.status_code == 303
    assert returned.headers["location"] == "/super-admin"
    assert admin.get("/super-admin").status_code == 200


def test_delete_store_requires_csrf_and_removes_store(client, db_session):
    admin, csrf, _ = _login_super_admin(client, db_session)
    store = Store(name="Delete Me", slug="delete-me")
    db_session.add(store)
    db_session.commit()

    rejected = admin.post(f"/super-admin/stores/{store.id}/delete")
    assert rejected.status_code == 403
    accepted = admin.post(
        f"/super-admin/stores/{store.id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert db_session.query(Store).filter(Store.id == store.id).one_or_none() is None
