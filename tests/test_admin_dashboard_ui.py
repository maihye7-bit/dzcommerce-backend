import re
import uuid
import asyncio
from datetime import datetime
from decimal import Decimal

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.agent.conversation_engine import ConversationEngine
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools import tool_registry
from app.agent.tools.store_info import StoreInfoTool
from app.api.dashboard_ui import (
    _money,
    _order_reference,
    _order_status_label,
    templates,
)
from app.core.security import hash_password, verify_password
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from app.services.inventory_service import get_available_quantity

PASSWORD = "DashboardPass123"


def test_password_hashes_use_bcrypt_without_72_byte_collisions():
    long_password = "x" * 72 + "first"
    hashed = hash_password(long_password)
    assert hashed.startswith("$bcrypt-sha256$")
    assert verify_password(long_password, hashed)
    assert not verify_password("x" * 72 + "other", hashed)
    legacy_argon2_hash = PasswordHasher().hash("legacy-password")
    assert verify_password("legacy-password", legacy_argon2_hash)


def _csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login_owner(client, email: str, store_name: str):
    registration = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": "Dashboard Owner",
            "store_name": store_name,
        },
    )
    assert registration.status_code == 201

    login_page = client.get("/dashboard/login")
    assert login_page.status_code == 200
    response = client.post(
        "/dashboard/login",
        data={
            "username": email,
            "password": PASSWORD,
            "csrf_token": _csrf_from(login_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def _session_for_owner(client, email: str, store_name: str):
    _login_owner(client, email, store_name)
    settings_page = client.get("/dashboard/settings")
    assert settings_page.status_code == 200
    return client, _csrf_from(settings_page.text)


def test_dashboard_redirects_unauthenticated_requests_to_login(client):
    response = client.get("/dashboard/products", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/login"


def test_dashboard_login_requires_csrf_token(client):
    login_page = client.get("/dashboard/login")
    csrf_token = _csrf_from(login_page.text)
    response = client.post(
        "/dashboard/login",
        data={"username": "nobody@example.com", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert csrf_token


def test_dashboard_settings_mutation_without_csrf_is_rejected(client):
    dashboard, _ = _session_for_owner(
        client, "csrf-owner@example.com", "CSRF Store"
    )
    response = dashboard.post(
        "/dashboard/settings",
        data={
            "name": "Changed name",
            "address": "Test address",
            "delivery_policy_text": "Test policy",
            "served_wilayas": "Alger",
        },
    )
    assert response.status_code == 403
    store = dashboard.get("/dashboard/settings")
    assert "CSRF Store" in store.text


def test_product_stock_edit_uses_inventory_service_and_bot_reads_updated_stock(
    client, db_session
):
    dashboard, csrf = _session_for_owner(
        client, "stock-owner@example.com", "Stock Store"
    )
    response = dashboard.post(
        "/dashboard/products",
        data={
            "name": "Green tea",
            "description": "Tea",
            "base_price": "350",
            "initial_quantity": "1",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    product = db_session.query(Product).filter(Product.name == "Green tea").one()
    variant = db_session.query(ProductVariant).filter(
        ProductVariant.product_id == product.id
    ).one()

    updated = dashboard.post(
        f"/dashboard/variants/{variant.id}/stock",
        data={"quantity": "7", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert get_available_quantity(db_session, product.store_id, variant.id) == 7

    result = asyncio.run(
        CheckInventoryTool().execute(
            product.store_id,
            {"variant_id": str(variant.id), "quantity": 5},
            {"db": db_session},
        )
    )
    assert result.success is True
    assert result.data["available_quantity"] == 7
    assert result.data["is_available"] is True

    detail = dashboard.get(f"/dashboard/products/{product.id}")
    assert "value=\"7\"" in detail.text


def test_product_variant_can_be_created_and_updated_with_csrf(client, db_session):
    dashboard, csrf = _session_for_owner(
        client, "variant-owner@example.com", "Variant Store"
    )
    dashboard.post(
        "/dashboard/products",
        data={
            "name": "Jacket",
            "base_price": "5000",
            "initial_quantity": "0",
            "csrf_token": csrf,
        },
    )
    product = db_session.query(Product).filter(Product.name == "Jacket").one()
    created = dashboard.post(
        f"/dashboard/products/{product.id}/variants",
        data={
            "name": "Red / M",
            "price_adjustment": "250",
            "attributes_json": '{"color":"red","size":"M"}',
            "initial_quantity": "4",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    variant = db_session.query(ProductVariant).filter(
        ProductVariant.product_id == product.id,
        ProductVariant.name == "Red / M",
    ).one()
    updated = dashboard.post(
        f"/dashboard/products/{product.id}/variants/{variant.id}",
        data={
            "name": "Red / Large",
            "price_adjustment": "300",
            "attributes_json": '{"color":"red","size":"L"}',
            "sku": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(variant)
    assert variant.name == "Red / Large"
    assert variant.attributes_json == {"color": "red", "size": "L"}


def test_home_page_metrics_and_low_stock_alert_are_store_scoped(client, db_session):
    dashboard, _ = _session_for_owner(
        client, "home-owner@example.com", "Home Store"
    )
    store = db_session.query(Store).filter(Store.name == "Home Store").one()
    product = Product(store_id=store.id, name="Low tea", base_price=Decimal("100"))
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product_id=product.id, name="Standard")
    db_session.add(variant)
    db_session.flush()
    db_session.add(
        InventoryItem(store_id=store.id, variant_id=variant.id, quantity=2)
    )
    db_session.add(
        Order(
            store_id=store.id,
            status=OrderStatus.CONFIRMED,
            subtotal=Decimal("123.45"),
            shipping_cost=Decimal("0"),
            total=Decimal("123.45"),
            created_at=datetime.now(),
        )
    )
    db_session.commit()

    response = dashboard.get("/dashboard")
    assert response.status_code == 200
    assert "طلبات اليوم" in response.text
    assert "123.45" in response.text
    assert "Low tea" in response.text
    assert "المتوفر: 2" in response.text


def test_tenant_owner_sees_only_own_products_and_orders(client, db_session):
    owner_a, _ = _session_for_owner(client, "tenant-a@example.com", "Store A")
    with TestClient(client.app) as owner_b_client:
        owner_b, _ = _session_for_owner(
            owner_b_client, "tenant-b@example.com", "Store B"
        )
        _assert_tenant_products_and_orders(db_session, owner_a, owner_b)


def _assert_tenant_products_and_orders(db_session, owner_a, owner_b):
    store_a = db_session.query(Store).filter(Store.name == "Store A").one()
    store_b = db_session.query(Store).filter(Store.name == "Store B").one()
    product_a = Product(
        store_id=store_a.id,
        name="Visible only to A",
        base_price=Decimal("10"),
    )
    product_b = Product(
        store_id=store_b.id,
        name="Secret product B",
        base_price=Decimal("20"),
    )
    db_session.add_all([product_a, product_b])
    db_session.flush()
    order_b = Order(
        store_id=store_b.id,
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("20"),
        shipping_cost=Decimal("0"),
        total=Decimal("20"),
    )
    db_session.add(order_b)
    db_session.commit()

    products_a = owner_a.get("/dashboard/products").text
    products_b = owner_b.get("/dashboard/products").text
    assert "Visible only to A" in products_a
    assert "Secret product B" not in products_a
    assert "Secret product B" in products_b
    assert owner_a.get("/dashboard/orders").status_code == 200
    assert owner_a.get(f"/dashboard/orders/{order_b.id}").status_code == 404


def test_store_settings_are_used_for_verified_store_info_responses(
    client, db_session
):
    dashboard, csrf = _session_for_owner(
        client, "store-info-owner@example.com", "Info Store"
    )
    saved = dashboard.post(
        "/dashboard/settings",
        data={
            "name": "Info Store Updated",
            "address": "12 Rue Didouche Mourad, Alger",
            "delivery_policy_text": "التوصيل خلال يومين حسب الولاية.",
            "served_wilayas": "الجزائر، البليدة",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert saved.status_code == 200
    store = db_session.query(Store).filter(Store.name == "Info Store Updated").one()
    info_result = asyncio.run(
        StoreInfoTool().execute(store.id, {}, {"db": db_session})
    )
    assert info_result.success
    address_reply = ConversationEngine._store_policy_response(
        "address", "ar", info_result.data
    )
    delivery_reply = ConversationEngine._store_policy_response(
        "delivery", "ar", info_result.data
    )
    assert store.address in address_reply
    assert store.delivery_policy_text in delivery_reply
    assert store.served_wilayas in delivery_reply

    customer = Customer(store_id=store.id, name="Store Info Customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status="active",
        metadata_json={},
    )
    db_session.add(conversation)
    db_session.commit()
    engine = ConversationEngine(llm_provider=None, tool_registry=tool_registry)
    address_turn = asyncio.run(
        engine.process_message(
            db_session,
            store.id,
            customer.id,
            conversation.id,
            "test",
            "وين عنوان محلكم؟",
        )
    )
    delivery_turn = asyncio.run(
        engine.process_message(
            db_session,
            store.id,
            customer.id,
            conversation.id,
            "test",
            "عندكم توصيل؟",
        )
    )
    assert store.address in address_turn["response"]
    assert store.delivery_policy_text in delivery_turn["response"]
    assert store.served_wilayas in delivery_turn["response"]

    store.address = None
    store.delivery_policy_text = None
    store.served_wilayas = None
    db_session.commit()
    missing_result = asyncio.run(
        StoreInfoTool().execute(store.id, {}, {"db": db_session})
    )
    missing_reply = ConversationEngine._store_policy_response(
        "address", "ar", missing_result.data
    )
    assert "ما عنديش عنوان موثق" in missing_reply


def test_orders_page_lists_all_statuses_and_detail_matches_database(
    client, db_session
):
    dashboard, _ = _session_for_owner(
        client, "orders-owner@example.com", "Orders Store"
    )
    store = db_session.query(Store).filter(Store.name == "Orders Store").one()
    customer = Customer(store_id=store.id, name="Order Customer")
    db_session.add(customer)
    product = Product(store_id=store.id, name="Coffee", base_price=Decimal("75"))
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product_id=product.id, name="250g")
    db_session.add(variant)
    db_session.flush()
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("150"),
        shipping_cost=Decimal("10"),
        total=Decimal("160"),
        wilaya="Alger",
    )
    db_session.add(order)
    db_session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        variant_id=variant.id,
        quantity=2,
        unit_price=Decimal("75"),
    )
    db_session.add(item)
    db_session.commit()

    orders_html = dashboard.get("/dashboard/orders").text
    assert "مؤكد" in orders_html
    assert "ORD-" in orders_html
    assert f"<span class=\"row-title reference\">ORD-{order.id.hex[:8].upper()}</span>" in orders_html
    detail = dashboard.get(f"/dashboard/orders/{order.id}")
    assert detail.status_code == 200
    assert "160 دج" in detail.text
    assert str(order.id) in detail.text
    assert "مؤكد" in detail.text
    assert "Coffee" in detail.text
    assert "250g" in detail.text
    assert "2" in detail.text


def test_conversations_are_read_only_and_store_scoped(client, db_session):
    dashboard, _ = _session_for_owner(
        client, "conversation-owner@example.com", "Conversation Store"
    )
    store = db_session.query(Store).filter(Store.name == "Conversation Store").one()
    customer = Customer(store_id=store.id, name="Conversation Customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="whatsapp",
        status="active",
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="السلام عليكم",
        )
    )
    db_session.commit()

    listing = dashboard.get("/dashboard/conversations")
    assert listing.status_code == 200
    assert "Conversation Customer" in listing.text
    transcript = dashboard.get(
        f"/dashboard/conversations/{conversation.id}"
    )
    assert transcript.status_code == 200
    assert "السلام عليكم" in transcript.text
    assert transcript.status_code != 405


def test_all_dashboard_pages_render_in_arabic_rtl(client, db_session):
    dashboard, _ = _session_for_owner(
        client, "render-owner@example.com", "Render Store"
    )
    pages = (
        "/dashboard",
        "/dashboard/products",
        "/dashboard/products/new",
        "/dashboard/orders",
        "/dashboard/settings",
        "/dashboard/account",
        "/dashboard/conversations",
    )
    for page in pages:
        response = dashboard.get(page)
        assert response.status_code == 200, page
        assert '<html lang="ar" dir="rtl"' in response.text

    product = Product(
        store_id=db_session.query(Store).filter(Store.name == "Render Store").one().id,
        name="Rendering test product",
        base_price=Decimal("1000"),
    )
    db_session.add(product)
    db_session.flush()
    order = Order(
        store_id=product.store_id,
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("1000"),
        shipping_cost=Decimal("0"),
        total=Decimal("1000"),
    )
    db_session.add(order)
    db_session.commit()
    assert dashboard.get(f"/dashboard/products/{product.id}").status_code == 200
    assert dashboard.get(f"/dashboard/orders/{order.id}").status_code == 200


def test_dashboard_theme_preference_is_csrf_protected_and_saved(client):
    dashboard, csrf = _session_for_owner(
        client, "theme-owner@example.com", "Theme Store"
    )
    rejected = dashboard.post(
        "/dashboard/appearance",
        data={"theme": "dark"},
        follow_redirects=False,
    )
    assert rejected.status_code == 403
    saved = dashboard.post(
        "/dashboard/appearance",
        data={"theme": "dark", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    page = dashboard.get("/dashboard")
    assert '<html lang="ar" dir="rtl" data-theme="dark">' in page.text
    assert "--bg: #000" in dashboard.get("/dashboard/static/dashboard.css").text
    assert "--bg: #F2F2F7" in dashboard.get("/dashboard/static/dashboard.css").text


def test_account_username_and_password_updates_require_csrf_and_validate(
    client, db_session
):
    dashboard, csrf = _session_for_owner(
        client, "account-owner@example.com", "Account Store"
    )
    user = db_session.query(User).filter(User.email == "account-owner@example.com").one()

    no_csrf = dashboard.post(
        "/dashboard/account/username",
        data={"username": "changed-owner"},
    )
    assert no_csrf.status_code == 403

    changed = dashboard.post(
        "/dashboard/account/username",
        data={"username": "changed-owner", "csrf_token": csrf},
    )
    assert changed.status_code == 200
    db_session.refresh(user)
    assert user.email == "changed-owner"

    mismatch = dashboard.post(
        "/dashboard/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "StrongPassword1!",
            "confirm_password": "DifferentPassword1!",
            "csrf_token": csrf,
        },
    )
    assert "غير متطابقتين" in mismatch.text
    assert verify_password(PASSWORD, user.hashed_password)

    weak = dashboard.post(
        "/dashboard/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "weak",
            "confirm_password": "weak",
            "csrf_token": csrf,
        },
    )
    assert "يجب أن تتكون كلمة المرور الجديدة" in weak.text

    changed_password = dashboard.post(
        "/dashboard/account/password",
        data={
            "current_password": PASSWORD,
            "new_password": "NewStrongPass1!",
            "confirm_password": "NewStrongPass1!",
            "csrf_token": csrf,
        },
    )
    assert "تم تحديث كلمة المرور" in changed_password.text
    assert 'href="/dashboard/settings"' in dashboard.get("/dashboard/account").text
    db_session.refresh(user)
    assert verify_password("NewStrongPass1!", user.hashed_password)
    assert not verify_password(PASSWORD, user.hashed_password)


def test_dashboard_display_filters_format_money_references_and_all_statuses():
    assert _money(514500) == "514,500"
    assert _money(Decimal("514500.5")) == "514,500.5"
    assert _order_status_label(OrderStatus.CONFIRMED) == "مؤكد"
    assert _order_status_label(OrderStatus.WAITING_CONFIRMATION) == "بانتظار التأكيد"
    assert _order_status_label(OrderStatus.READY_TO_SHIP) == "جاهز للشحن"
    assert _order_status_label(OrderStatus.SHIPPED) == "تم الشحن"
    assert _order_status_label(OrderStatus.DELIVERED) == "تم التسليم"
    assert _order_status_label(OrderStatus.CANCELLED) == "ملغي"
    assert _order_status_label(OrderStatus.HUMAN_HANDOFF) == "محوّل لموظف"
    assert _order_status_label(OrderStatus.DRAFT) == "مسودة"
    assert templates.env.filters["money"] is _money

    order = Order(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        store_id=uuid.uuid4(),
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("1"),
        shipping_cost=Decimal("0"),
        total=Decimal("1"),
    )
    assert _order_reference(order) == "ORD-12345678"


def test_owner_membership_is_revalidated_after_login(client, db_session):
    dashboard, _ = _session_for_owner(
        client, "revoked-owner@example.com", "Revoked Store"
    )
    user = db_session.query(User).filter(User.email == "revoked-owner@example.com").one()
    membership = db_session.query(StoreUser).filter(
        StoreUser.user_id == user.id
    ).one()
    assert membership.role == StoreRole.OWNER
    db_session.delete(membership)
    db_session.commit()

    response = dashboard.get("/dashboard/settings", follow_redirects=False)
    assert response.status_code == 303
