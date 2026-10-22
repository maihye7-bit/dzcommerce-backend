import uuid
from decimal import Decimal

from app.core.security import create_access_token
from app.models.ai_usage_event import AIUsageEvent
from app.services.usage_service import record_usage
from tests.helpers import auth_headers, get_first_store_id, register_and_get_token


def test_record_usage_creates_event_with_provider_usage(db_session):
    store_id = uuid.uuid4()
    event = record_usage(
        db=db_session,
        store_id=store_id,
        provider="qwen",
        model="qwen-max",
        input_tokens=120,
        output_tokens=30,
        latency_ms=450,
        commit=False,
    )

    assert event.store_id == store_id
    assert event.provider == "qwen"
    assert event.model == "qwen-max"
    assert event.input_tokens == 120
    assert event.output_tokens == 30
    assert event.total_tokens == 150
    assert event.estimated_cost == Decimal("0.00042")
    assert event.latency_ms == 450
    assert db_session.query(AIUsageEvent).filter_by(id=event.id).one() is event


def test_usage_events_are_scoped_by_store_id(client, db_session):
    own_token = register_and_get_token(
        client, "usage-owner-a@example.com", store_name="Usage Store A"
    )
    other_token = register_and_get_token(
        client, "usage-owner-b@example.com", store_name="Usage Store B"
    )
    own_store_id = uuid.UUID(get_first_store_id(client, own_token))
    other_store_id = uuid.UUID(get_first_store_id(client, other_token))
    record_usage(
        db_session,
        own_store_id,
        "qwen",
        "qwen-max",
        10,
        5,
        100,
        commit=False,
    )
    record_usage(
        db_session,
        other_store_id,
        "qwen",
        "qwen-max",
        100,
        50,
        200,
        commit=False,
    )
    db_session.commit()

    response = client.get(
        f"/api/dashboard/usage?store_id={own_store_id}",
        headers=auth_headers(own_token),
    )

    assert response.status_code == 200
    assert response.json()["total_events"] == 1
    assert response.json()["total_tokens"] == 15


def test_dashboard_usage_returns_store_aggregates(client, db_session):
    token = register_and_get_token(
        client, "usage-aggregate@example.com", store_name="Usage Aggregate Store"
    )
    store_id = uuid.UUID(get_first_store_id(client, token))
    record_usage(
        db_session,
        store_id,
        "qwen",
        "qwen-max",
        1000,
        500,
        250,
        commit=False,
    )
    record_usage(
        db_session,
        store_id,
        "qwen",
        "qwen-max",
        100,
        50,
        150,
        commit=False,
    )
    db_session.commit()

    response = client.get(
        f"/api/dashboard/usage?store_id={store_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_events": 2,
        "total_input_tokens": 1100,
        "total_output_tokens": 550,
        "total_tokens": 1650,
        "estimated_cost_usd": 0.0055,
        "events_today": 2,
    }


def test_dashboard_usage_returns_zeros_without_events(client):
    token = register_and_get_token(
        client, "usage-empty@example.com", store_name="Empty Usage Store"
    )
    store_id = uuid.UUID(get_first_store_id(client, token))

    response = client.get(
        f"/api/dashboard/usage?store_id={store_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_events": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "events_today": 0,
    }


def test_dashboard_usage_requires_authentication(client):
    response = client.get(f"/api/dashboard/usage?store_id={uuid.uuid4()}")

    assert response.status_code == 401
