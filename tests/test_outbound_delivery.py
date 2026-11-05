import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.config import settings
from app.models.channel_identity import ChannelIdentity
from app.models.channel_account import ChannelAccount
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.outbound_delivery import OutboundDelivery
from app.models.store import Store
from app.models.store_meta_token import StoreMetaToken
from app.services import channel_service, outbound_delivery
from app.services.meta_token_security import encrypt_meta_token
from app.services.messenger_media import MessengerDeliveryResult


@pytest.fixture(autouse=True)
def use_test_meta_encryption_key(monkeypatch):
    monkeypatch.setattr(
        settings,
        "SOCIAL_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )


def _create_channel_customer(db, external_account_id, external_user_id):
    store = Store(name="Identity store", slug=f"identity-{uuid.uuid4()}")
    db.add(store)
    db.flush()
    customer = channel_service.resolve_channel_customer(
        db,
        store.id,
        "facebook",
        external_account_id,
        external_user_id,
    )
    return store, customer


def _queue_text(
    db,
    *,
    channel="facebook",
    fallback_for_id=None,
    external_account_id="page-or-ig-account",
    recipient_external_id="external-recipient",
):
    store = Store(name="Delivery store", slug=f"delivery-{uuid.uuid4()}")
    db.add(store)
    db.flush()
    customer = Customer(store_id=store.id, name="Customer")
    db.add(customer)
    db.flush()
    db.add(
        ChannelAccount(
            store_id=store.id,
            channel=channel,
            external_account_id=external_account_id,
            is_active=True,
        )
    )
    db.add(
        StoreMetaToken(
            store_id=store.id,
            page_id=external_account_id,
            instagram_page_id=external_account_id,
            page_name="Test page",
            access_token=encrypt_meta_token("test-token"),
        )
    )
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel=channel,
        status=ConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.flush()
    delivery = outbound_delivery.enqueue_delivery(
        db,
        conversation_id=conversation.id,
        channel=channel,
        external_account_id=external_account_id,
        recipient_external_id=recipient_external_id,
        payload_type="text",
        payload={"text": "Saved reply"},
        fallback_for_id=fallback_for_id,
    )
    db.commit()
    return delivery


def test_channel_identity_keeps_external_id_separate_from_phone(db_session):
    store, customer = _create_channel_customer(
        db_session, "page-a", "messenger-user"
    )
    customer.phone = "0550123456"
    db_session.commit()

    next_message_customer = channel_service.resolve_channel_customer(
        db_session,
        store.id,
        "facebook",
        "page-a",
        "messenger-user",
    )
    identity = (
        db_session.query(ChannelIdentity)
        .filter(
            ChannelIdentity.store_id == store.id,
            ChannelIdentity.channel == "facebook",
            ChannelIdentity.external_account_id == "page-a",
            ChannelIdentity.external_user_id == "messenger-user",
        )
        .one()
    )

    assert next_message_customer.id == customer.id
    assert next_message_customer.phone == "0550123456"
    assert identity.external_user_id == "messenger-user"


def test_channel_identity_is_scoped_by_store_and_meta_account(db_session):
    store_a, customer_a = _create_channel_customer(
        db_session, "same-page", "same-user"
    )
    store_b, customer_b = _create_channel_customer(
        db_session, "same-page", "same-user"
    )
    another_account_customer = channel_service.resolve_channel_customer(
        db_session, store_a.id, "facebook", "another-page", "same-user"
    )
    db_session.commit()

    assert customer_a.id != customer_b.id
    assert another_account_customer.id != customer_a.id


@pytest.mark.asyncio
async def test_transient_delivery_is_persisted_then_retried_without_agent_work(
    db_session, monkeypatch
):
    delivery = _queue_text(db_session)
    responses = iter(
        [
            MessengerDeliveryResult(
                False, status_code=503, failure_code="graph_api_rejected", retryable=True
            ),
            MessengerDeliveryResult(True, status_code=200),
        ]
    )
    calls = []

    async def send_text(recipient_id, text, _access_token):
        calls.append((recipient_id, text))
        return next(responses)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)

    first_result = await outbound_delivery.dispatch_one(db_session)
    pending = db_session.query(OutboundDelivery).filter_by(id=delivery.id).one()
    assert first_result is False
    assert pending.status == "pending"
    assert pending.attempt_count == 1
    assert pending.next_attempt_at.replace(tzinfo=timezone.utc) > datetime.now(
        timezone.utc
    )

    pending.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    second_result = await outbound_delivery.dispatch_one(db_session)
    sent = db_session.query(OutboundDelivery).filter_by(id=delivery.id).one()

    assert second_result is True
    assert sent.status == "sent"
    assert sent.attempt_count == 2
    assert calls == [
        ("external-recipient", "Saved reply"),
        ("external-recipient", "Saved reply"),
    ]


@pytest.mark.asyncio
async def test_permanent_delivery_error_is_terminal(db_session, monkeypatch):
    delivery = _queue_text(db_session)
    calls = 0

    async def reject(_recipient_id, _text, _access_token):
        nonlocal calls
        calls += 1
        return MessengerDeliveryResult(
            False, status_code=403, failure_code="graph_error_permission", retryable=False
        )

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", reject)

    assert await outbound_delivery.dispatch_one(db_session) is False
    assert await outbound_delivery.dispatch_one(db_session) is None
    failed = db_session.query(OutboundDelivery).filter_by(id=delivery.id).one()
    assert failed.status == "failed"
    assert failed.failure_kind == "permanent"
    assert failed.attempt_count == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_instagram_text_reply_uses_account_scoped_sender(db_session, monkeypatch):
    delivery = _queue_text(db_session, channel="instagram")
    calls = []

    async def send_instagram(account_id, recipient_id, text, access_token):
        calls.append((account_id, recipient_id, text, access_token))
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_instagram_text", send_instagram)

    assert await outbound_delivery.dispatch_one(db_session) is True
    assert calls == [
        ("page-or-ig-account", "external-recipient", "Saved reply", "test-token")
    ]
    assert (
        db_session.query(OutboundDelivery).filter_by(id=delivery.id).one().status
        == "sent"
    )


def test_pending_delivery_survives_session_recreation(db_session):
    delivery = _queue_text(db_session)
    delivery_id = delivery.id
    bind = db_session.get_bind()
    replacement_session = sessionmaker(bind=bind)()
    try:
        restored = (
            replacement_session.query(OutboundDelivery)
            .filter_by(id=delivery_id)
            .one()
        )
        assert restored.status == "pending"
        assert restored.payload_json["text"] == "Saved reply"
    finally:
        replacement_session.close()


@pytest.mark.asyncio
async def test_permanent_image_failure_queues_a_text_fallback(db_session, monkeypatch):
    store = Store(name="Image fallback", slug=f"image-fallback-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="Customer")
    db_session.add(customer)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=store.id,
            channel="facebook",
            external_account_id="page-id",
            is_active=True,
        )
    )
    db_session.add(
        StoreMetaToken(
            store_id=store.id,
            page_id="page-id",
            page_name="Test page",
            access_token=encrypt_meta_token("test-token"),
        )
    )
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
    )
    db_session.add(conversation)
    db_session.flush()
    image_delivery = outbound_delivery.enqueue_delivery(
        db_session,
        conversation_id=conversation.id,
        channel="facebook",
        external_account_id="page-id",
        recipient_external_id="psid",
        payload_type="image",
        payload={
            "url": "https://shop.example/image",
            "fallback_text": "تعذر إرسال الصورة الآن.",
        },
    )
    db_session.commit()
    sent_fallbacks = []

    async def reject_image(_recipient_id, _url, _access_token):
        return MessengerDeliveryResult(
            False, status_code=400, failure_code="window_closed", retryable=False
        )

    async def send_fallback(recipient_id, text, _access_token):
        sent_fallbacks.append((recipient_id, text))
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_image", reject_image)
    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_fallback)

    assert await outbound_delivery.dispatch_due_deliveries(db_session, limit=2) == 1
    failed_image = (
        db_session.query(OutboundDelivery).filter_by(id=image_delivery.id).one()
    )
    fallback = (
        db_session.query(OutboundDelivery)
        .filter(OutboundDelivery.fallback_for_id == image_delivery.id)
        .one()
    )

    assert failed_image.status == "failed"
    assert fallback.status == "sent"
    assert sent_fallbacks == [("psid", "تعذر إرسال الصورة الآن.")]


@pytest.mark.asyncio
async def test_two_dispatchers_cannot_claim_same_delivery_concurrently(
    tmp_path, monkeypatch
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'outbound-claims.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    setup = sessions()
    delivery = _queue_text(setup)
    delivery_id = delivery.id
    setup.close()

    active = 0
    max_active = 0

    async def send_text(_recipient_id, _text, _access_token):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)
    first_session, second_session = sessions(), sessions()
    try:
        outcomes = await asyncio.gather(
            outbound_delivery.dispatch_one(first_session),
            outbound_delivery.dispatch_one(second_session),
        )
        assert sorted(value for value in outcomes if value is not None) == [True]
        assert max_active == 1
        assert (
            first_session.query(OutboundDelivery)
            .filter_by(id=delivery_id)
            .one()
            .status
            == "sent"
        )
    finally:
        first_session.close()
        second_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_channel_account_identifier_is_not_in_customer_phone(db_session):
    store, customer = _create_channel_customer(
        db_session, "meta-page-id", "meta-psid"
    )
    identity = (
        db_session.query(ChannelIdentity)
        .filter(
            ChannelIdentity.store_id == store.id,
            ChannelIdentity.customer_id == customer.id,
        )
        .one()
    )
    assert customer.phone is None
    assert identity.external_account_id == "meta-page-id"
    assert identity.external_user_id == "meta-psid"


@pytest.mark.asyncio
async def test_facebook_deliveries_use_each_stores_exact_page_token(
    db_session, monkeypatch
):
    first = _queue_text(
        db_session,
        external_account_id="page-one",
        recipient_external_id="recipient-one",
    )
    second = _queue_text(
        db_session,
        external_account_id="page-two",
        recipient_external_id="recipient-two",
    )
    first_store_id = (
        db_session.query(Conversation.store_id)
        .filter(Conversation.id == first.conversation_id)
        .scalar()
    )
    second_store_id = (
        db_session.query(Conversation.store_id)
        .filter(Conversation.id == second.conversation_id)
        .scalar()
    )
    first_credentials = (
        db_session.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == first_store_id)
        .one()
    )
    second_credentials = (
        db_session.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == second_store_id)
        .one()
    )
    first_credentials.access_token = encrypt_meta_token("store-one-token")
    second_credentials.access_token = encrypt_meta_token("store-two-token")
    db_session.commit()
    used_tokens = {}

    async def send_text(recipient_id, _text, access_token):
        used_tokens[recipient_id] = access_token
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", send_text)

    assert await outbound_delivery.dispatch_due_deliveries(db_session, limit=2) == 2
    assert used_tokens == {
        "recipient-one": "store-one-token",
        "recipient-two": "store-two-token",
    }


@pytest.mark.asyncio
async def test_instagram_requires_matching_store_account_token(db_session, monkeypatch):
    delivery = _queue_text(
        db_session,
        channel="instagram",
        external_account_id="ig-account",
    )
    credentials = (
        db_session.query(StoreMetaToken)
        .join(Conversation, Conversation.store_id == StoreMetaToken.store_id)
        .filter(Conversation.id == delivery.conversation_id)
        .one()
    )
    credentials.instagram_page_id = "ig-account"
    credentials.access_token = encrypt_meta_token("instagram-page-token")
    db_session.commit()
    received = []

    async def send_instagram(account_id, _recipient_id, _text, access_token):
        received.append((account_id, access_token))
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_instagram_text", send_instagram)

    assert await outbound_delivery.dispatch_one(db_session) is True
    assert received == [("ig-account", "instagram-page-token")]


@pytest.mark.asyncio
async def test_missing_or_foreign_account_token_fails_without_global_fallback(
    db_session, monkeypatch
):
    delivery = _queue_text(db_session, external_account_id="unmatched-page")
    store_id = (
        db_session.query(Conversation.store_id)
        .filter(Conversation.id == delivery.conversation_id)
        .scalar()
    )
    credentials = (
        db_session.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == store_id)
        .one()
    )
    credentials.page_id = "different-page"
    credentials.access_token = encrypt_meta_token("must-not-be-used")
    other_store = Store(name="Other credential store", slug=f"other-token-{uuid.uuid4()}")
    db_session.add(other_store)
    db_session.flush()
    db_session.add(
        StoreMetaToken(
            store_id=other_store.id,
            page_id="unmatched-page",
            page_name="Foreign page",
            access_token=encrypt_meta_token("foreign-store-token"),
        )
    )
    db_session.commit()
    sends = []

    async def should_not_send(*_args):
        sends.append(True)
        return MessengerDeliveryResult(True, status_code=200)

    monkeypatch.setattr(outbound_delivery, "send_messenger_text", should_not_send)

    assert await outbound_delivery.dispatch_one(db_session) is False
    failed = db_session.query(OutboundDelivery).filter_by(id=delivery.id).one()
    assert failed.status == "failed"
    assert failed.failure_kind == "permanent"
    assert failed.last_error == "meta_account_credential_unavailable"
    assert sends == []


def test_legacy_identity_stays_unbound_and_its_conversation_is_preserved(db_session):
    store = Store(name="Legacy identity", slug=f"legacy-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    legacy_customer = Customer(store_id=store.id, name="Legacy customer")
    db_session.add(legacy_customer)
    db_session.flush()
    legacy_conversation = Conversation(
        store_id=store.id,
        customer_id=legacy_customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
    )
    db_session.add(legacy_conversation)
    db_session.add(
        ChannelIdentity(
            store_id=store.id,
            customer_id=legacy_customer.id,
            channel="facebook",
            external_account_id=None,
            external_user_id="same-user",
        )
    )
    db_session.commit()

    accountless_customer = channel_service.resolve_channel_customer(
        db_session, store.id, "facebook", None, "same-user"
    )
    account_scoped_customer = channel_service.resolve_channel_customer(
        db_session, store.id, "facebook", "known-page", "same-user"
    )
    db_session.commit()

    assert accountless_customer.id == legacy_customer.id
    assert account_scoped_customer.id != legacy_customer.id
    assert (
        db_session.query(Conversation)
        .filter_by(id=legacy_conversation.id, customer_id=legacy_customer.id)
        .one()
    )
    legacy_identity = (
        db_session.query(ChannelIdentity)
        .filter(
            ChannelIdentity.customer_id == legacy_customer.id,
            ChannelIdentity.external_user_id == "same-user",
        )
        .one()
    )
    assert legacy_identity.external_account_id is None


def test_concurrent_accountless_identity_creation_reuses_one_customer(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-identities.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    setup = sessions()
    store = Store(name="Concurrent legacy", slug=f"concurrent-{uuid.uuid4()}")
    setup.add(store)
    setup.commit()
    store_id = store.id
    setup.close()
    barrier = threading.Barrier(2)

    def resolve_identity():
        session = sessions()
        try:
            barrier.wait()
            customer = channel_service.resolve_channel_customer(
                session, store_id, "facebook", None, "shared-user"
            )
            customer_id = customer.id
            session.commit()
            return customer_id
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            customer_ids = list(executor.map(lambda _index: resolve_identity(), range(2)))
        verify = sessions()
        try:
            assert customer_ids[0] == customer_ids[1]
            assert verify.query(Customer).filter_by(store_id=store_id).count() == 1
            assert (
                verify.query(ChannelIdentity)
                .filter_by(
                    store_id=store_id,
                    channel="facebook",
                    external_account_id=None,
                    external_user_id="shared-user",
                )
                .count()
                == 1
            )
        finally:
            verify.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
