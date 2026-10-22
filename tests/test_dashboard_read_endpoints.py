import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from tests.helpers import auth_headers, get_first_store_id, register_and_get_token


def _seed_order(db_session, store_id, lines, created_at=None):
    total = sum((price * quantity for _, _, price, quantity in lines), Decimal("0"))
    order = Order(
        store_id=store_id,
        status=OrderStatus.CONFIRMED,
        subtotal=total,
        total=total,
        shipping_cost=Decimal("0"),
        created_at=created_at,
    )
    db_session.add(order)
    db_session.flush()

    items = []
    for product_name, variant_name, unit_price, quantity in lines:
        product = Product(
            store_id=store_id,
            name=product_name,
            base_price=unit_price,
        )
        db_session.add(product)
        db_session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name=variant_name,
        )
        db_session.add(variant)
        db_session.flush()
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            variant_id=variant.id,
            quantity=quantity,
            unit_price=unit_price,
        )
        db_session.add(item)
        items.append(item)

    db_session.commit()
    return order, items


def test_dashboard_order_detail_returns_own_order_with_item_names(client, db_session):
    token = register_and_get_token(
        client, "dashboard-detail-owner@example.com", store_name="Detail Store"
    )
    store_id = uuid.UUID(get_first_store_id(client, token))
    order, items = _seed_order(
        db_session,
        store_id,
        [("Winter coat", "Blue / M", Decimal("1250.50"), 2)],
    )

    response = client.get(
        f"/api/dashboard/orders/{order.id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(order.id)
    assert body["total"] == 2501.0
    assert body["items"] == [
        {
            "id": str(items[0].id),
            "product_id": str(items[0].product_id),
            "product_name": "Winter coat",
            "variant_id": str(items[0].variant_id),
            "variant_name": "Blue / M",
            "quantity": 2,
            "unit_price": 1250.5,
            "line_total": 2501.0,
        }
    ]


def test_dashboard_order_detail_rejects_cross_store_order(client, db_session):
    own_token = register_and_get_token(
        client, "dashboard-detail-a@example.com", store_name="Detail Store A"
    )
    other_token = register_and_get_token(
        client, "dashboard-detail-b@example.com", store_name="Detail Store B"
    )
    other_store_id = uuid.UUID(get_first_store_id(client, other_token))
    order, _ = _seed_order(
        db_session,
        other_store_id,
        [("Private item", "Default", Decimal("10"), 1)],
    )

    response = client.get(
        f"/api/dashboard/orders/{order.id}",
        headers=auth_headers(own_token),
    )

    assert response.status_code == 404


def test_dashboard_order_detail_returns_404_for_missing_order(client):
    token = register_and_get_token(
        client, "dashboard-detail-missing@example.com", store_name="Missing Order Store"
    )

    response = client.get(
        f"/api/dashboard/orders/{uuid.uuid4()}",
        headers=auth_headers(token),
    )

    assert response.status_code == 404


def test_dashboard_summary_orders_today_is_store_scoped(client, db_session):
    token = register_and_get_token(
        client, "dashboard-today-a@example.com", store_name="Today Store A"
    )
    other_token = register_and_get_token(
        client, "dashboard-today-b@example.com", store_name="Today Store B"
    )
    store_id = uuid.UUID(get_first_store_id(client, token))
    other_store_id = uuid.UUID(get_first_store_id(client, other_token))
    today = datetime.combine(date.today(), time(hour=12))
    yesterday = datetime.combine(date.today() - timedelta(days=1), time(hour=12))
    _seed_order(
        db_session, store_id, [("Today item", "Default", Decimal("10"), 1)], today
    )
    _seed_order(
        db_session, store_id, [("Old item", "Default", Decimal("20"), 1)], yesterday
    )
    _seed_order(
        db_session,
        other_store_id,
        [("Other store item", "Default", Decimal("30"), 1)],
        today,
    )

    response = client.get(
        f"/api/dashboard/stats?store_id={store_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["orders_today"] == 1


def test_dashboard_top_products_ranks_by_units_sold_and_returns_revenue(
    client, db_session
):
    token = register_and_get_token(
        client, "dashboard-top-products@example.com", store_name="Top Products Store"
    )
    store_id = uuid.UUID(get_first_store_id(client, token))
    _seed_order(
        db_session,
        store_id,
        [
            ("Product A", "Red", Decimal("20"), 3),
            ("Product B", "Large", Decimal("10"), 5),
            ("Product C", "Standard", Decimal("100"), 2),
            ("Product D", "Default", Decimal("5"), 1),
            ("Product E", "Default", Decimal("7"), 1),
            ("Product F", "Default", Decimal("9"), 1),
        ],
    )

    response = client.get(
        f"/api/dashboard/analytics/top-products?store_id={store_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 5
    assert [item["product_name"] for item in results] == [
        "Product B",
        "Product A",
        "Product C",
        "Product D",
        "Product E",
    ]
    assert results[0]["variant_name"] == "Large"
    assert results[0]["count"] == 5
    assert results[0]["revenue"] == 50.0


def test_dashboard_top_products_rejects_unauthenticated_access(client):
    response = client.get(
        f"/api/dashboard/analytics/top-products?store_id={uuid.uuid4()}"
    )

    assert response.status_code == 401
