"""
Phase 6 Tests: Channel-Agnostic Social Commerce Foundation.
Covers adapters, normalization, identity mapping, tenant isolation,
idempotency, and Unicode safety.
"""
import uuid
import pytest
import asyncio

from app.channels.adapters.mock_facebook import MockFacebookAdapter
from app.channels.adapters.mock_instagram import MockInstagramAdapter
from app.channels.adapters.mock_whatsapp import MockWhatsAppAdapter
from app.channels.router import ChannelRouter
from app.schemas.channel_events import InboundEvent, OutboundMessage
from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.services import channel_service


# ============================================================
# ADAPTER NORMALIZATION TESTS
# ============================================================

class TestFacebookAdapter:
    def setup_method(self):
        self.adapter = MockFacebookAdapter()

    def test_normalize_messenger_message(self):
        event = self.adapter.normalize_inbound_event({
            "event_type": "message_received",
            "external_message_id": "fb_msg_001",
            "external_conversation_id": "fb_conv_001",
            "external_user_id": "fb_user_123",
            "customer_name": "Ahmed",
            "message_text": "salam wach kayen l produit?",
        })
        assert event.channel == "facebook"
        assert event.event_type == "message_received"
        assert event.message_text == "salam wach kayen l produit?"
        assert event.external_user_id == "fb_user_123"

    def test_normalize_comment(self):
        event = self.adapter.normalize_inbound_event({
            "event_type": "comment_created",
            "external_message_id": "fb_cmt_001",
            "external_conversation_id": "fb_post_999",
            "external_user_id": "fb_user_456",
            "message_text": "ch7al hada?",
            "post_id": "post_999",
        })
        assert event.event_type == "comment_created"
        assert event.metadata.get("post_id") == "post_999"

    def test_missing_text_raises(self):
        with pytest.raises(ValueError, match="missing message_text"):
            self.adapter.normalize_inbound_event({
                "event_type": "message_received",
                "external_message_id": "x",
                "external_conversation_id": "x",
                "external_user_id": "x",
            })

    @pytest.mark.asyncio
    async def test_send_message(self):
        result = await self.adapter.send_message(OutboundMessage(
            channel="facebook", recipient_external_id="fb_user_123",
            text="Marhba bik!",
        ))
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_reply_to_comment(self):
        result = await self.adapter.reply_to_comment(OutboundMessage(
            channel="facebook", recipient_external_id="fb_user_456",
            text="Prix: 5000 DZD", reply_to_external_id="fb_cmt_001",
        ))
        assert result["status"] == "sent"


class TestInstagramAdapter:
    def setup_method(self):
        self.adapter = MockInstagramAdapter()

    def test_normalize_dm(self):
        event = self.adapter.normalize_inbound_event({
            "event_type": "message_received",
            "external_message_id": "ig_dm_001",
            "external_conversation_id": "ig_conv_001",
            "external_user_id": "ig_user_789",
            "message_text": "n7ab nchri had l jacket",
        })
        assert event.channel == "instagram"
        assert event.message_text == "n7ab nchri had l jacket"

    def test_normalize_comment(self):
        event = self.adapter.normalize_inbound_event({
            "event_type": "comment_created",
            "external_message_id": "ig_cmt_001",
            "external_conversation_id": "ig_reel_555",
            "external_user_id": "ig_user_101",
            "message_text": "win rakom?",
        })
        assert event.event_type == "comment_created"

    @pytest.mark.asyncio
    async def test_send_dm(self):
        result = await self.adapter.send_message(OutboundMessage(
            channel="instagram", recipient_external_id="ig_user_789",
            text="Kayn! Ch7al t7taj?",
        ))
        assert result["status"] == "sent"


class TestWhatsAppAdapter:
    def setup_method(self):
        self.adapter = MockWhatsAppAdapter()

    def test_normalize_message(self):
        event = self.adapter.normalize_inbound_event({
            "external_message_id": "wa_msg_001",
            "external_conversation_id": "213550123456",
            "external_user_id": "213550123456",
            "customer_name": "Karim",
            "message_text": "3andkom livraison?",
        })
        assert event.channel == "whatsapp"
        assert event.event_type == "message_received"
        assert event.message_text == "3andkom livraison?"

    @pytest.mark.asyncio
    async def test_send_message(self):
        result = await self.adapter.send_message(OutboundMessage(
            channel="whatsapp", recipient_external_id="213550123456",
            text="Oui, 500 DZD pour Alger.",
        ))
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_comment_not_supported(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.reply_to_comment(OutboundMessage(
                channel="whatsapp", recipient_external_id="x",
                text="test", reply_to_external_id="x",
            ))


# ============================================================
# ROUTER TESTS
# ============================================================

class TestChannelRouter:
    def test_register_and_get(self):
        router = ChannelRouter()
        fb = MockFacebookAdapter()
        router.register(fb)
        assert router.get_adapter("facebook") is fb

    def test_duplicate_registration_raises(self):
        router = ChannelRouter()
        router.register(MockFacebookAdapter())
        with pytest.raises(ValueError, match="already registered"):
            router.register(MockFacebookAdapter())

    def test_unknown_channel_raises(self):
        router = ChannelRouter()
        with pytest.raises(ValueError, match="No adapter"):
            router.get_adapter("telegram")

    def test_normalize_dispatches_correctly(self):
        router = ChannelRouter()
        router.register(MockFacebookAdapter())
        router.register(MockWhatsAppAdapter())
        event = router.normalize("whatsapp", {
            "external_message_id": "w1",
            "external_conversation_id": "c1",
            "external_user_id": "u1",
            "message_text": "test",
        })
        assert event.channel == "whatsapp"

    def test_registered_channels(self):
        router = ChannelRouter()
        router.register(MockFacebookAdapter())
        router.register(MockInstagramAdapter())
        router.register(MockWhatsAppAdapter())
        channels = sorted(router.registered_channels)
        assert channels == ["facebook", "instagram", "whatsapp"]


# ============================================================
# CHANNEL SERVICE INTEGRATION TESTS
# ============================================================

class TestChannelServiceIntegration:
    """Tests that use db_session to verify full integration."""

    def _make_store(self, db):
        store_id = uuid.uuid4()
        return store_id

    def test_creates_customer_and_identity_on_first_message(self, db_session):
        store_id = self._make_store(db_session)
        event = InboundEvent(
            channel="facebook", event_type="message_received",
            external_message_id="ext_001",
            external_conversation_id="conv_ext_001",
            external_user_id="fb_u1", customer_name="Amine",
            message_text="salam",
        )
        result = channel_service.handle_inbound_event(db_session, store_id, event)
        assert result["skipped"] is False
        assert result["customer_id"] is not None

        # Verify identity was created
        identity = (
            db_session.query(ChannelIdentity)
            .filter(ChannelIdentity.external_user_id == "fb_u1")
            .first()
        )
        assert identity is not None
        assert identity.channel == "facebook"

    def test_same_customer_multiple_identities(self, db_session):
        store_id = self._make_store(db_session)

        # First message from Facebook
        fb_event = InboundEvent(
            channel="facebook", event_type="message_received",
            external_message_id="fb_001",
            external_conversation_id="fb_conv",
            external_user_id="fb_u1", customer_name="Sara",
            message_text="hello from fb",
        )
        fb_result = channel_service.handle_inbound_event(db_session, store_id, fb_event)
        customer_id = fb_result["customer_id"]

        # Link WhatsApp identity to same customer manually
        wa_identity = ChannelIdentity(
            store_id=store_id, customer_id=uuid.UUID(customer_id),
            channel="whatsapp", external_user_id="213550999999",
        )
        db_session.add(wa_identity)
        db_session.commit()

        # Verify both identities point to same customer
        identities = (
            db_session.query(ChannelIdentity)
            .filter(ChannelIdentity.customer_id == uuid.UUID(customer_id))
            .all()
        )
        assert len(identities) == 2
        channels = {i.channel for i in identities}
        assert channels == {"facebook", "whatsapp"}

    def test_idempotency_duplicate_message_skipped(self, db_session):
        store_id = self._make_store(db_session)
        event = InboundEvent(
            channel="instagram", event_type="message_received",
            external_message_id="unique_id_999",
            external_conversation_id="ig_conv",
            external_user_id="ig_u1", message_text="test duplicate",
        )
        r1 = channel_service.handle_inbound_event(db_session, store_id, event)
        assert r1["skipped"] is False

        # Same event again -> must be skipped
        r2 = channel_service.handle_inbound_event(db_session, store_id, event)
        assert r2["skipped"] is True

    def test_unicode_darija_arabizi_preserved(self, db_session):
        store_id = self._make_store(db_session)
        texts = [
            "salam wach kayen",
            "n7ab nchri had l jacket",
            "شحال الثمن؟",
            "ma3lich 3tini prix",
            "مرحبا بكم في متجرنا",
        ]
        for i, text in enumerate(texts):
            event = InboundEvent(
                channel="whatsapp", event_type="message_received",
                external_message_id=f"unicode_test_{i}",
                external_conversation_id="wa_conv",
                external_user_id="wa_u1", message_text=text,
            )
            result = channel_service.handle_inbound_event(db_session, store_id, event)
            assert result["skipped"] is False

        # Verify all messages stored with exact text
        messages = db_session.query(Message).filter(
            Message.external_message_id.like("unicode_test_%")
        ).all()
        stored_texts = {m.content for m in messages}
        for text in texts:
            assert text in stored_texts

    def test_tenant_isolation_customers(self, db_session):
        store_a = uuid.uuid4()
        store_b = uuid.uuid4()

        event_a = InboundEvent(
            channel="facebook", event_type="message_received",
            external_message_id="iso_fb_001",
            external_conversation_id="iso_conv",
            external_user_id="same_ext_id", customer_name="User A",
            message_text="hello from store A",
        )
        channel_service.handle_inbound_event(db_session, store_a, event_a)

        # Same external_user_id but different store -> different customer
        event_b = InboundEvent(
            channel="facebook", event_type="message_received",
            external_message_id="iso_fb_002",
            external_conversation_id="iso_conv_b",
            external_user_id="same_ext_id", customer_name="User B",
            message_text="hello from store B",
        )
        channel_service.handle_inbound_event(db_session, store_b, event_b)

        # Verify two separate customers were created
        cust_a = (
            db_session.query(ChannelIdentity)
            .filter(ChannelIdentity.store_id == store_a,
                    ChannelIdentity.external_user_id == "same_ext_id")
            .first()
        )
        cust_b = (
            db_session.query(ChannelIdentity)
            .filter(ChannelIdentity.store_id == store_b,
                    ChannelIdentity.external_user_id == "same_ext_id")
            .first()
        )
        assert cust_a.customer_id != cust_b.customer_id

    def test_empty_customer_history_works(self, db_session):
        store_id = self._make_store(db_session)
        event = InboundEvent(
            channel="whatsapp", event_type="message_received",
            external_message_id="empty_hist_001",
            external_conversation_id="wa_new_conv",
            external_user_id="new_user_xyz",
            message_text="first message ever",
        )
        result = channel_service.handle_inbound_event(db_session, store_id, event)
        assert result["skipped"] is False
        assert result["conversation_id"] is not None
