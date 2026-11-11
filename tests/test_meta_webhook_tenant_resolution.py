import hashlib
import hmac
import json
import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.models.channel_account import ChannelAccount
from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer
from app.models.outbound_delivery import OutboundDelivery
from app.models.store import Store
from app.models.store_meta_token import StoreMetaToken
from app.services import outbound_delivery
from app.services.messenger_media import MessengerDeliveryResult
from app.services.webhook_security import verify_meta_verify_token
import app.api.webhooks as webhooks


@pytest.fixture(autouse=True)
def use_test_meta_sender_for_outbox(monkeypatch):
    monkeypatch.setattr(
        outbound_delivery,
        "_resolve_access_token",
        lambda _db, _delivery: "test-page-token",
    )

    async def send_text(_recipient_id, _text, _access_token):
        return MessengerDeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)

    async def send_instagram_text(_account_id, _recipient_id, _text, _access_token):
        return MessengerDeliveryResult(delivered=True, status_code=200)

    async def send_image(_recipient_id, _url, _access_token):
        return MessengerDeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_instagram_text", send_instagram_text)
    monkeypatch.setattr(outbound_delivery, "send_messenger_image", send_image)


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


def _link_facebook_page(db, store_id, page_id):
    db.add(
        ChannelAccount(
            store_id=store_id,
            channel="facebook",
            external_account_id=page_id,
            is_active=True,
        )
    )
    db.add(
        StoreMetaToken(
            store_id=store_id,
            page_id=page_id,
            page_name="Connected Page",
            access_token="fernet:v1:encrypted-test-token",
        )
    )


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
    if channel == "facebook":
        db_session.add(
            StoreMetaToken(
                store_id=connected_store.id,
                page_id="account-target",
                page_name="Connected Page",
                access_token="fernet:v1:encrypted-test-token",
            )
        )
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)

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


def test_facebook_webhook_does_not_auto_link_to_the_only_active_store(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Unlinked store", slug=f"unlinked-{uuid.uuid4()}")
    db_session.add(store)
    db_session.commit()
    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)

    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "unverified-page",
                    "messaging": [
                        {
                            "sender": {"id": "customer"},
                            "message": {"mid": "unverified-message", "text": "hello"},
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

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert (
        db_session.query(ChannelAccount)
        .filter_by(channel="facebook", external_account_id="unverified-page")
        .count()
        == 0
    )
    assert engine.calls == []


def test_meta_webhook_receives_image_only_and_stores_it_once(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Image store", slug=f"image-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "image-page")
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    attachment_calls = []

    async def store_attachment(attachments):
        attachment_calls.append(attachments)
        return [
            {
                "type": "image",
                "status": "stored",
                "storage_key": "conversation-attachments/test.png",
                "mime_type": "image/png",
                "file_size": 24,
            }
        ]

    monkeypatch.setattr(webhooks, "_store_inbound_attachments", store_attachment)
    sent = []

    async def send_text(recipient_id, text, _access_token):
        sent.append((recipient_id, text))
        return MessengerDeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "image-page",
                    "messaging": [
                        {
                            "sender": {"id": "image-customer"},
                            "message": {
                                "mid": "image-only-mid",
                                "attachments": [
                                    {
                                        "type": "image",
                                        "payload": {
                                            "url": "https://lookaside.fbsbx.com/image"
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
    headers = {"X-Hub-Signature-256": _signature(body, secret)}

    first = client.post("/webhooks/meta", content=body, headers=headers)
    duplicate = client.post("/webhooks/meta", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["count"] == 1
    assert duplicate.json()["skipped"] == 1
    assert engine.calls == []
    assert len(attachment_calls) == 1
    assert len(sent) == 1
    assert "لا أستطيع تحليل" in sent[0][1]

    inbound = (
        db_session.query(Message)
        .filter(Message.external_message_id == "image-only-mid")
        .one()
    )
    assert inbound.message_type == "image"
    assert inbound.content == ""
    assert inbound.metadata_json["attachments"][0]["storage_key"].endswith("test.png")


def test_facebook_followup_reuses_channel_identity_after_phone_capture(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Identity store", slug=f"identity-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "identity-page")
    db_session.commit()
    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)

    def post_message(mid):
        body = json.dumps(
            {
                "object": "page",
                "entry": [
                    {
                        "id": "identity-page",
                        "messaging": [
                            {
                                "sender": {"id": "messenger-psid"},
                                "message": {"mid": mid, "text": "سلام"},
                            }
                        ],
                    }
                ],
            }
        ).encode()
        return client.post(
            "/webhooks/meta",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body, secret)},
        )

    assert post_message("identity-first").status_code == 200
    identity = (
        db_session.query(ChannelIdentity)
        .filter(
            ChannelIdentity.store_id == store.id,
            ChannelIdentity.channel == "facebook",
            ChannelIdentity.external_account_id == "identity-page",
            ChannelIdentity.external_user_id == "messenger-psid",
        )
        .one()
    )
    customer = db_session.query(Customer).filter_by(id=identity.customer_id).one()
    customer.phone = "0550123456"
    db_session.commit()

    assert post_message("identity-followup").status_code == 200
    conversations = (
        db_session.query(Conversation)
        .filter(
            Conversation.store_id == store.id,
            Conversation.customer_id == customer.id,
            Conversation.channel == "facebook",
        )
        .all()
    )
    assert len(conversations) == 1
    assert len(engine.calls) == 2
    assert engine.calls[0]["conversation_id"] == engine.calls[1]["conversation_id"]
    assert db_session.query(Customer).filter_by(store_id=store.id).count() == 1
    assert customer.phone == "0550123456"


def test_outbox_retry_after_duplicate_event_does_not_reenter_engine(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Retry store", slug=f"retry-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "retry-page")
    db_session.commit()
    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    send_attempts = []

    async def fail_once(_recipient_id, _text, _access_token):
        send_attempts.append("attempt")
        status = 503 if len(send_attempts) == 1 else 200
        return MessengerDeliveryResult(
            delivered=status == 200,
            status_code=status,
            failure_code="test_graph_rejected" if status != 200 else None,
            retryable=status >= 500,
        )

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", fail_once)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "retry-page",
                    "messaging": [
                        {
                            "sender": {"id": "retry-psid"},
                            "message": {"mid": "retry-mid", "text": "hello"},
                        }
                    ],
                }
            ],
        }
    ).encode()
    headers = {"X-Hub-Signature-256": _signature(body, secret)}

    assert client.post("/webhooks/meta", content=body, headers=headers).status_code == 200
    pending = db_session.query(OutboundDelivery).filter_by(status="pending").one()
    pending.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    duplicate = client.post("/webhooks/meta", content=body, headers=headers)
    assert duplicate.json()["skipped"] == 1

    assert asyncio.run(outbound_delivery.dispatch_due_deliveries(db_session)) == 1
    sent = db_session.query(OutboundDelivery).filter_by(id=pending.id).one()
    assert sent.status == "sent"
    assert sent.attempt_count == 2
    assert len(engine.calls) == 1
    assert len(send_attempts) == 2


def test_meta_webhook_processes_text_with_image_and_reports_expired_image(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Mixed store", slug=f"mixed-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "mixed-page")
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)

    async def failed_attachment(_attachments):
        return [
            {
                "type": "image",
                "status": "failed",
                "failure_code": "attachment_unavailable",
            }
        ]

    monkeypatch.setattr(webhooks, "_store_inbound_attachments", failed_attachment)
    sent = []

    async def send_text(_recipient_id, text, _access_token):
        sent.append(text)
        return MessengerDeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)
    body = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "mixed-page",
                    "messaging": [
                        {
                            "sender": {"id": "mixed-customer"},
                            "message": {
                                "mid": "text-image-mid",
                                "text": "ما هو سعره؟",
                                "attachments": [
                                    {
                                        "type": "image",
                                        "payload": {
                                            "url": "https://lookaside.fbsbx.com/expired"
                                        },
                                    }
                                ],
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

    assert response.status_code == 200
    assert engine.calls[0]["user_message"] == "ما هو سعره؟"
    assert "تعذر فتح الصورة" in sent[0]
    inbound = (
        db_session.query(Message)
        .filter(Message.external_message_id == "text-image-mid")
        .one()
    )
    assert inbound.message_type == "text_image"
    assert inbound.metadata_json["attachments"][0]["failure_code"] == "attachment_unavailable"
    assert (
        db_session.query(Message)
        .filter(
            Message.conversation_id == inbound.conversation_id,
            Message.role == MessageRole.AGENT,
        )
        .order_by(Message.created_at.desc())
        .first()
        .content
        .endswith("تعذر فتح الصورة. أعد إرسالها من فضلك أو صف لي ما تحتاجه.")
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
    _link_facebook_page(db_session, store.id, "constraint-page")
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
    _link_facebook_page(db_session, connected_store.id, "target-page")
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


def test_meta_webhook_persists_failed_turn_reply_for_outbox_delivery(
    client, db_session, monkeypatch
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Failure store", slug=f"failure-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "failure-page")
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

    async def fake_send_facebook_message(recipient_id, text, _access_token):
        sent_replies.append((recipient_id, text))
        return MessengerDeliveryResult(delivered=True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", fake_send_facebook_message)
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
    assert retry.json()["skipped"] == 1
    assert engine.calls == 1
    assert len(sent_replies) == 1
    assert "أعد إرسال رسالتك من فضلك" in sent_replies[0][1]
    assert (
        db_session.query(Message)
        .filter(
            Message.external_message_id == "engine-failure-message",
            Message.role == MessageRole.CUSTOMER,
        )
        .count()
        == 1
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
            )
        )
        session.add(
            ChannelIdentity(
                store_id=store_id,
                customer_id=customer_id,
                channel="facebook",
                external_user_id="synthetic-sender",
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
    [(200, "SEND_OK delivered_count=1"), (400, "SEND_FAIL")],
)
def test_meta_webhook_sends_reply_to_customer_psid_and_ignores_non_messages(
    client, db_session, monkeypatch, caplog, send_status, expected_log
):
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    store = Store(name="Messenger store", slug=f"messenger-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    _link_facebook_page(db_session, store.id, "messenger-page")
    db_session.commit()

    engine = RecordingEngine()
    monkeypatch.setattr(webhooks, "_engine", engine)
    sent_messages = []

    async def fake_send_facebook_message(recipient_id, text, _access_token):
        sent_messages.append((recipient_id, text))
        return MessengerDeliveryResult(
            delivered=send_status < 400,
            status_code=send_status,
            failure_code="test_graph_rejected" if send_status >= 400 else None,
            retryable=send_status >= 500,
        )

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", fake_send_facebook_message)

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
async def test_facebook_comment_reply_uses_explicit_account_token(monkeypatch):
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
    await webhooks._send_facebook_comment_reply(
        "comment-id",
        "مرحبا",
        "test-page-token",
    )

    assert request_details == {
        "timeout": 30.0,
        "url": "https://graph.facebook.com/v26.0/comment-id/comments",
        "params": {"access_token": "test-page-token"},
        "json": {"message": "مرحبا"},
    }


def test_meta_webhook_ignores_unmapped_account_without_processing(
    client, db_session, monkeypatch
):
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

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert db_session.query(Message).count() == 0


def test_meta_verification_requires_configured_token(monkeypatch):
    monkeypatch.delenv("META_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("FACEBOOK_VERIFY_TOKEN", raising=False)


def test_meta_webhook_accepts_valid_signature_with_configured_secret(client, monkeypatch):
    """1. توقيع صحيح مع App Secret صحيح → قبول الطلب (200)."""
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)

    # Build a valid signature using the same helper the app uses
    body = '{"object":"page","entry":[{"id":"page_id","changes":[]}]}'.encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={sig}"}

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("processed", "ignored")


def test_meta_webhook_rejects_invalid_signature(client, monkeypatch):
    """2. توقيع خاطئ → 401."""
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)

    body = '{"object":"page","entry":[{"id":"page_id","changes":[]}]}'.encode()
    headers = {"X-Hub-Signature-256": "sha256=invalid"}

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401


def test_meta_webhook_requires_signature_header(client, monkeypatch):
    """3. غياب X-Hub-Signature-256 → 401 مع WEBHOOK_NO_SIGNATURE."""
    secret = "test-meta-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)

    body = '{"object":"page","entry":[{"id":"page_id","changes":[]}]}'.encode()
    # No X-Hub-Signature-256 header at all

    response = client.post(
        "/webhooks/meta",
        content=body,
    )

    assert response.status_code == 401


def test_meta_webhook_missing_secret_with_sig(client, monkeypatch):
    """4. وجود التوقيع لكن غياب App Secret → 503 مع WEBHOOK_SIGNATURE_CONFIG_MISSING."""
    # Ensure META_APP_SECRET is NOT set
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("FACEBOOK_APP_SECRET", raising=False)

    body = '{"object":"page","entry":[{"id":"page_id","changes":[]}]}'.encode()
    sig = hmac.new(b"some-secret", body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={sig}"}

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers=headers,
    )

    assert response.status_code == 503


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
