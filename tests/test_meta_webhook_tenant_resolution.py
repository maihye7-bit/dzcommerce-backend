import hashlib
import hmac
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.models.channel_account import ChannelAccount
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer
from app.models.store import Store
from app.services.webhook_security import verify_meta_verify_token
import app.api.webhooks as webhooks


class RecordingEngine:
    def __init__(self):
        self.calls = []

    async def process_message(self, **kwargs):
        self.calls.append(kwargs)
        kwargs["db"].add(
            Message(
                conversation_id=kwargs["conversation_id"],
                role=MessageRole.AGENT,
                content="تم استلام رسالتك.",
            )
        )
        kwargs["db"].commit()
        return {"response": "تم استلام رسالتك.", "tool_calls": []}


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.parametrize(
    ("platform_object", "channel"),
    [("page", "facebook"), ("instagram", "instagram")],
)
def test_meta_webhook_uses_bound_store_and_preserves_idempotency(
    client, db_session, monkeypatch, platform_object, channel
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    first_store = Store(name="First store", slug=f"first-{uuid.uuid4()}")
    connected_store = Store(name="Connected store", slug=f"connected-{uuid.uuid4()}")
    db_session.add_all([first_store, connected_store])
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=connected_store.id,
            channel=channel,
            external_account_id="account-target",
            is_active=True,
        )
    )
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)

    async def fake_send_facebook_message(recipient_id, text):
        return SimpleNamespace(status_code=200, is_success=True, text="{}")

    monkeypatch.setattr(
        webhooks,
        "_send_facebook_message",
        fake_send_facebook_message,
    )
    body = json.dumps(
        {
            "object": platform_object,
            "entry": [
                {
                    "id": "account-target",
                    "messaging": [
                        {
                            "sender": {"id": "customer-external-id"},
                            "message": {"mid": "meta-message-1", "text": "سلام"},
                        }
                    ],
                }
            ],
        }
    ).encode()
    headers = {"X-Hub-Signature-256": _signature(body, secret)}

    first_response = client.post("/webhooks/meta", content=body, headers=headers)
    duplicate_response = client.post("/webhooks/meta", content=body, headers=headers)

    assert first_response.status_code == 200
    assert first_response.json()["count"] == 1
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["skipped"] == 1
    assert len(engine.calls) == 1
    assert engine.calls[0]["store_id"] == connected_store.id
    assert engine.calls[0]["channel"] == channel

    conversations = (
        db_session.query(Conversation)
        .filter(Conversation.customer_id == engine.calls[0]["customer_id"])
        .all()
    )
    assert len(conversations) == 1
    assert conversations[0].store_id == connected_store.id
    assert conversations[0].channel == channel
    assert (
        db_session.query(Message)
        .filter(Message.external_message_id == "meta-message-1")
        .count()
        == 1
    )


def test_meta_webhook_rejects_invalid_signature_before_database_access(
    client, monkeypatch
):
    monkeypatch.setenv("META_APP_SECRET", "test-meta-secret")
    response = client.post(
        "/webhooks/meta",
        content=b'{"object":"page","entry":[]}',
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )

    assert response.status_code == 401


def test_meta_webhook_does_not_treat_unrelated_integrity_error_as_duplicate(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Constraint store", slug=f"constraint-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=store.id,
            channel="facebook",
            external_account_id="constraint-page",
            is_active=True,
        )
    )
    customer = Customer(store_id=store.id, name="Existing customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status="active",
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="سلام",
            external_message_id="existing-message-id",
        )
    )
    db_session.commit()
    db_session.execute(
        text("CREATE UNIQUE INDEX uq_test_message_content ON messages(content)")
    )
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "constraint-page",
                    "messaging": [
                        {
                            "sender": {"id": "new-customer"},
                            "message": {
                                "mid": "different-message-id",
                                "text": "سلام",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={"X-Hub-Signature-256": _signature(body, secret)},
    )

    assert response.status_code == 500
    assert engine.calls == []
    assert (
        db_session.query(Message)
        .filter(Message.external_message_id == "different-message-id")
        .count()
        == 0
    )


@pytest.mark.parametrize("collision_scope", ["other_tenant", "other_channel"])
def test_meta_webhook_does_not_skip_message_id_from_another_scope(
    client, db_session, monkeypatch, collision_scope
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    connected_store = Store(
        name="Target store",
        slug=f"target-{uuid.uuid4()}",
    )
    other_store = (
        Store(name="Other store", slug=f"other-{uuid.uuid4()}")
        if collision_scope == "other_tenant"
        else connected_store
    )
    db_session.add(connected_store)
    if other_store is not connected_store:
        db_session.add(other_store)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=connected_store.id,
            channel="facebook",
            external_account_id="target-page",
            is_active=True,
        )
    )
    other_customer = Customer(store_id=other_store.id, name="Other customer")
    db_session.add(other_customer)
    db_session.flush()
    other_conversation = Conversation(
        store_id=other_store.id,
        customer_id=other_customer.id,
        channel=(
            "facebook" if collision_scope == "other_tenant" else "instagram"
        ),
        status="active",
    )
    db_session.add(other_conversation)
    db_session.flush()
    db_session.add(
        Message(
            conversation_id=other_conversation.id,
            role=MessageRole.CUSTOMER,
            content="same external ID, different scope",
            external_message_id="scope-collision-id",
        )
    )
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "target-page",
                    "messaging": [
                        {
                            "sender": {"id": "target-customer"},
                            "message": {
                                "mid": "scope-collision-id",
                                "text": "سلام",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={"X-Hub-Signature-256": _signature(body, secret)},
    )

    assert response.status_code == 500
    assert "skipped" not in response.json()
    assert engine.calls == []
    assert (
        db_session.query(Message)
        .filter(Message.external_message_id == "scope-collision-id")
        .count()
        == 1
    )


def test_meta_webhook_rolls_back_failed_turn_and_allows_retry(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setattr(webhooks, "FACEBOOK_PAGE_ACCESS_TOKEN", "test-page-token")
    store = Store(name="Failure store", slug=f"failure-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=store.id,
            channel="facebook",
            external_account_id="failure-page",
            is_active=True,
        )
    )
    db_session.commit()

    class FailOnceEngine:
        def __init__(self):
            self.calls = 0

        async def process_message(self, **kwargs):
            self.calls += 1
            raise RuntimeError("synthetic engine failure")

    engine = FailOnceEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    sent_replies = []

    async def fake_send_facebook_message(recipient_id, text):
        sent_replies.append((recipient_id, text))
        return SimpleNamespace(
            status_code=200,
            is_success=True,
            text="{}",
        )

    monkeypatch.setattr(
        webhooks,
        "_send_facebook_message",
        fake_send_facebook_message,
    )
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "failure-page",
                    "messaging": [
                        {
                            "sender": {"id": "synthetic-failure-sender"},
                            "message": {
                                "mid": "engine-failure-message",
                                "text": "synthetic failure scenario",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    headers = {"X-Hub-Signature-256": _signature(body, secret)}

    first = client.post("/webhooks/meta", content=body, headers=headers)
    retry = client.post("/webhooks/meta", content=body, headers=headers)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["skipped"] == 0
    assert engine.calls == 2
    assert len(sent_replies) == 2
    assert "حدث خطأ تقني مؤقت" in sent_replies[0][1]
    assert (
        db_session.query(Message)
        .filter(
            Message.external_message_id == "engine-failure-message",
            Message.role == MessageRole.CUSTOMER,
        )
        .count()
        == 0
    )


def test_concurrent_inbound_message_claim_uses_database_unique_constraint(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'webhook-idempotency.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    store_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    with sessions.begin() as session:
        session.add(Store(id=store_id, name="Concurrent store", slug=str(store_id)))
        session.add(
            Customer(
                id=customer_id,
                store_id=store_id,
                name="Concurrent customer",
                phone="synthetic-sender",
            )
        )
        session.add(
            Conversation(
                id=conversation_id,
                store_id=store_id,
                customer_id=customer_id,
                channel="facebook",
                status="active",
            )
        )

    barrier = threading.Barrier(2)
    processing_calls = []
    processing_lock = threading.Lock()

    def deliver() -> bool:
        with sessions() as session:
            barrier.wait(timeout=10)
            inserted = webhooks._persist_inbound_message(
                db=session,
                conversation_id=conversation_id,
                store_id=store_id,
                channel="facebook",
                sender_id="synthetic-sender",
                text="concurrent test event",
                external_message_id="concurrent-external-id",
            )
            if inserted:
                with processing_lock:
                    processing_calls.append("processed")
                session.commit()
            assert session.is_active
            assert not session.in_transaction()
            return inserted

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: deliver(), range(2)))

        assert sorted(outcomes) == [False, True]
        assert processing_calls == ["processed"]
        with sessions() as session:
            assert (
                session.query(Message)
                .filter(
                    Message.external_message_id == "concurrent-external-id"
                )
                .count()
                == 1
            )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("send_status", "expected_log"),
    [(200, "SEND_OK status_code=200"), (400, "SEND_FAIL status_code=400")],
)
def test_meta_webhook_sends_reply_to_customer_psid_and_ignores_non_messages(
    client, db_session, monkeypatch, caplog, send_status, expected_log
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Messenger store", slug=f"messenger-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=store.id,
            channel="facebook",
            external_account_id="messenger-page",
            is_active=True,
        )
    )
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    sent_messages = []

    async def fake_send_facebook_message(recipient_id, text):
        sent_messages.append((recipient_id, text))
        return SimpleNamespace(
            status_code=send_status,
            is_success=send_status < 400,
            text='{"error":{"message":"test send result"}}',
        )

    monkeypatch.setattr(
        webhooks,
        "_send_facebook_message",
        fake_send_facebook_message,
    )
    monkeypatch.setattr(webhooks, "FACEBOOK_PAGE_ACCESS_TOKEN", "test-page-token")

    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "messenger-page",
                    "messaging": [
                        {
                            "sender": {"id": "customer-external-id"},
                            "message": {
                                "mid": "echo-message",
                                "text": "do not process this echo",
                                "is_echo": True,
                            },
                        },
                        {
                            "sender": {"id": "customer-external-id"},
                            "read": {"watermark": 123},
                        },
                        {
                            "sender": {"id": "customer-external-id"},
                            "delivery": {"mids": ["sent-message"]},
                        },
                        {
                            "sender": {"id": "customer-external-id"},
                            "message": {"mid": "incoming-message", "text": "سلام"},
                        },
                    ],
                }
            ],
        }
    ).encode()

    with caplog.at_level("DEBUG", logger=webhooks.__name__):
        response = client.post(
            "/webhooks/meta",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body, secret)},
        )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert len(engine.calls) == 1
    assert sent_messages == [("customer-external-id", "تم استلام رسالتك.")]
    assert expected_log in caplog.text
    assert "SIGNATURE_OK" in caplog.text
    assert "AGENT_REPLY" in caplog.text
    assert "SEND_ATTEMPT" in caplog.text
    assert "conversation_delivery" in caplog.text
    assert (
        f"response_candidates=1 responses_sent={int(send_status < 400)}"
        in caplog.text
    )
    assert "سلام" not in caplog.text

    saved_replies = (
        db_session.query(Message)
        .filter(
            Message.role == "agent",
            Message.content == "تم استلام رسالتك.",
        )
        .all()
    )
    assert len(saved_replies) == 1


@pytest.mark.asyncio
async def test_send_facebook_message_uses_page_token_and_v26_graph_api(monkeypatch):
    request_details = {}

    class FakeAsyncClient:
        def __init__(self, timeout):
            request_details["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, params, json):
            request_details.update(
                url=url,
                params=params,
                json=json,
            )
            return SimpleNamespace(status_code=200, is_success=True, text="{}")

    monkeypatch.setattr(webhooks.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(webhooks, "FACEBOOK_PAGE_ACCESS_TOKEN", "test-page-token")

    await webhooks._send_facebook_message("customer-psid", "مرحبا")

    assert request_details == {
        "timeout": 30.0,
        "url": "https://graph.facebook.com/v26.0/me/messages",
        "params": {"access_token": "test-page-token"},
        "json": {
            "recipient": {"id": "customer-psid"},
            "message": {"text": "مرحبا"},
        },
    }


def test_meta_webhook_rejects_unmapped_account(client, db_session, monkeypatch):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "unmapped-account",
                    "messaging": [
                        {
                            "sender": {"id": "customer"},
                            "message": {"mid": "unmapped-message", "text": "hello"},
                        }
                    ],
                }
            ],
        }
    ).encode()

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={"X-Hub-Signature-256": _signature(body, secret)},
    )

    assert response.status_code == 404
    assert db_session.query(Message).count() == 0


def test_meta_verification_requires_configured_token(monkeypatch):
    monkeypatch.delenv("META_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("FACEBOOK_VERIFY_TOKEN", raising=False)

    with pytest.raises(RuntimeError):
        verify_meta_verify_token("anything")


def test_production_settings_reject_default_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, ENV="production")


def test_production_settings_accept_legacy_jwt_environment_names(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_ALGORITHM", raising=False)
    monkeypatch.setenv("SECRET_KEY", "a" * 40)
    monkeypatch.setenv("ALGORITHM", "HS512")
    settings = Settings(
        _env_file=None,
        ENV="production",
    )

    assert settings.JWT_SECRET_KEY == "a" * 40
    assert settings.JWT_ALGORITHM == "HS512"
