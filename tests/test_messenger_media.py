import io
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app.channels.adapters.facebook_adapter import FacebookAdapter
from app.agent.conversation_engine import ConversationEngine
from app.agent.tools import tool_registry
from app.agent.tools.send_product_image import (
    SendProductImageTool,
    is_product_image_request,
)
from app.config import settings
from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.outbound_delivery import OutboundDelivery
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.store import Store
from app.services import inbound_attachments, messenger_media, product_image_storage
from app.services.inbound_attachments import InboundAttachmentError
from app.services.webhook_processor import _redact_webhook_payload


def _png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (4, 4), (20, 80, 120)).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_inbound_meta_image_is_validated_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", None)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", None)
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=_png_bytes(),
        )
    )
    monkeypatch.setattr(
        inbound_attachments.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    attachment = await inbound_attachments.download_and_store_meta_image(
        "https://lookaside.fbsbx.com/attachment"
    )

    assert attachment["status"] == "stored"
    assert attachment["mime_type"] == "image/png"
    assert product_image_storage.path_for_key(
        str(attachment["storage_key"])
    ).is_file()


@pytest.mark.asyncio
async def test_expired_meta_image_is_reported_without_persisting(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", None)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", None)
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, content=b"expired")
    )
    monkeypatch.setattr(
        inbound_attachments.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    with pytest.raises(InboundAttachmentError, match="attachment_unavailable"):
        await inbound_attachments.download_and_store_meta_image(
            "https://lookaside.fbsbx.com/expired"
        )
    assert not list(tmp_path.rglob("*.png"))


def test_public_product_image_url_requires_configured_https_host(monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_PUBLIC_DOMAIN", "shop.example.test")
    image_id = uuid.uuid4()

    assert messenger_media.build_public_product_image_url(
        f"/api/product-images/{image_id}/content"
    ) == f"https://shop.example.test/api/product-images/{image_id}/content"
    with pytest.raises(ValueError, match="configured public host"):
        messenger_media.build_public_product_image_url(
            f"https://localhost/api/product-images/{image_id}/content"
        )
    with pytest.raises(ValueError, match="supported public endpoint"):
        messenger_media.build_public_product_image_url(
            f"https://shop.example.test/private/{image_id}.png"
        )


@pytest.mark.asyncio
async def test_messenger_graph_api_sends_image_attachment_and_checks_delivery(
    monkeypatch,
):
    captured = {}
    real_async_client = httpx.AsyncClient

    def handle(request):
        captured["url"] = request.url
        captured["payload"] = json.loads(request.read())
        return httpx.Response(200, json={"recipient_id": "psid", "message_id": "m-1"})

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        messenger_media.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    result = await messenger_media.send_messenger_image(
        "psid",
        "https://shop.example.test/api/product-images/image-id/content",
        "test-token",
    )

    assert result.delivered is True
    assert result.status_code == 200
    assert captured["url"].host == "graph.facebook.com"
    assert str(captured["url"].copy_with(query=None)) == (
        "https://graph.facebook.com/v26.0/me/messages"
    )
    assert captured["url"].params["access_token"] == "test-token"
    assert captured["payload"] == {
        "recipient": {"id": "psid"},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {
                    "url": "https://shop.example.test/api/product-images/image-id/content"
                },
            }
        },
    }


@pytest.mark.asyncio
async def test_instagram_text_uses_account_scoped_graph_endpoint(monkeypatch):
    captured = {}
    real_async_client = httpx.AsyncClient

    def handle(request):
        captured["url"] = request.url
        captured["payload"] = json.loads(request.read())
        return httpx.Response(200, json={"recipient_id": "ig-user", "message_id": "m-2"})

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        messenger_media.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    result = await messenger_media.send_instagram_text(
        "ig-account",
        "ig-user",
        "تم استلام رسالتك.",
        "test-token",
    )

    assert result.delivered is True
    assert str(captured["url"].copy_with(query=None)) == (
        "https://graph.facebook.com/v26.0/ig-account/messages"
    )
    assert captured["url"].params["access_token"] == "test-token"
    assert captured["payload"] == {
        "recipient": {"id": "ig-user"},
        "message": {"text": "تم استلام رسالتك."},
    }


@pytest.mark.asyncio
async def test_send_product_image_queues_the_meta_identity_without_claiming_delivery(
    db_session, monkeypatch
):
    store = Store(name="Messenger image store", slug=f"messenger-image-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(
        store_id=store.id,
        name="Messenger customer",
        phone="0550123456",
    )
    db_session.add(customer)
    db_session.flush()
    product = Product(
        store_id=store.id,
        name="عباية",
        base_price=Decimal("1000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        external_conversation_id="customer-psid",
        metadata_json={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(product.id),
            "selected_product_name": product.name,
            "external_account_id": "messenger-page",
        },
    )
    db_session.add(conversation)
    db_session.add(
        ChannelIdentity(
            store_id=store.id,
            customer_id=customer.id,
            channel="facebook",
            external_account_id="messenger-page",
            external_user_id="customer-psid",
        )
    )
    image = ProductImage(
        store_id=store.id,
        product_id=product.id,
        storage_key="stores/test/image.png",
        image_url=f"/api/product-images/{uuid.uuid4()}/content",
        mime_type="image/png",
        file_size=20,
        is_primary=True,
        display_order=0,
    )
    db_session.add(image)
    db_session.commit()

    monkeypatch.setattr(settings, "RAILWAY_PUBLIC_DOMAIN", "shop.example.test")
    monkeypatch.setattr(
        product_image_storage,
        "read_image",
        lambda _storage_key: SimpleNamespace(is_file=lambda: True),
    )
    engine = ConversationEngine(None, tool_registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    response = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="ممكن صور المنتج",
        external_account_id="messenger-page",
        external_user_id="customer-psid",
    )

    assert response["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:send_product_image"
    )
    assert response["response"] == "سأرسل لك صورة المنتج الآن."
    image_delivery = (
        db_session.query(OutboundDelivery)
        .filter(OutboundDelivery.payload_type == "image")
        .one()
    )
    assert image_delivery.recipient_external_id == "customer-psid"
    assert image_delivery.payload_json["url"] == (
        f"https://shop.example.test{image.image_url}"
    )
    assert image_delivery.status == "pending"
    assert customer.phone == "0550123456"


@pytest.mark.asyncio
async def test_send_product_image_cannot_cross_store_boundary(db_session):
    first_store = Store(name="First image store", slug=f"first-image-{uuid.uuid4()}")
    second_store = Store(name="Second image store", slug=f"second-image-{uuid.uuid4()}")
    db_session.add_all([first_store, second_store])
    db_session.flush()
    customer = Customer(store_id=first_store.id, name="Customer", phone="psid")
    db_session.add(customer)
    db_session.flush()
    product = Product(
        store_id=second_store.id,
        name="Other store product",
        base_price=Decimal("1000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    conversation = Conversation(
        store_id=first_store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        metadata_json={"selected_product_id": str(product.id)},
    )
    db_session.add(conversation)
    db_session.commit()

    result = await SendProductImageTool().execute(
        store_id=first_store.id,
        arguments={"product_id": str(product.id)},
        context={
            "db": db_session,
            "conversation_id": conversation.id,
            "customer_id": customer.id,
            "channel": "facebook",
            "user_message": "أرسل لي صورة المنتج",
        },
    )

    assert result.success is False
    assert result.error_code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_vision_analysis_reads_only_stored_local_image(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", None)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", None)
    storage_key = "inbound/test.png"
    image_bytes = _png_bytes()
    product_image_storage.save_image(storage_key, image_bytes)

    class MockVisionProvider:
        def __init__(self):
            self.received = []

        async def describe_image(self, image, mime_type):
            self.received.append((image, mime_type))
            return "A blue ceramic mug."

    provider = MockVisionProvider()
    engine = ConversationEngine(None, tool_registry, vision_provider=provider)

    observations = await engine._analyze_inbound_images(
        [
            {
                "status": "stored",
                "storage_key": storage_key,
                "mime_type": "image/png",
            },
            {
                "status": "stored",
                "storage_key": "..\\outside.png",
                "mime_type": "image/png",
            },
        ]
    )

    assert observations == ["A blue ceramic mug."]
    assert provider.received == [(image_bytes, "image/png")]


def test_conversation_memory_persists_canonical_commerce_state(db_session):
    store = Store(name="Memory store", slug=f"memory-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(
        store_id=store.id,
        name="Memory customer",
        phone="0550123456",
    )
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        metadata_json={
            "commerce_stage": "DRAFT_PENDING",
            "selected_product_id": str(uuid.uuid4()),
            "selected_product_name": "حذاء",
            "selected_variant_id": str(uuid.uuid4()),
            "selected_attributes": {"color": "black", "size": "42"},
            "last_question_type": "CUSTOMER_DELIVERY_INFO",
            "recent_image_understanding": ["حذاء أزرق ظاهر في الصورة."],
        },
        active_draft_json={
            "draft_id": str(uuid.uuid4()),
            "items": [{"product_name": "حذاء", "quantity": 1}],
            "shipping_info": {"wilaya": "الجزائر"},
        },
    )
    db_session.add(conversation)
    db_session.commit()

    current_state = ConversationEngine._normalize_current_state(
        conversation,
        store.id,
    )
    ConversationEngine._refresh_conversation_memory(
        db_session,
        conversation,
        current_state,
        "order_create",
    )
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.query(Conversation).filter_by(id=conversation.id).one()
    memory = reloaded.metadata_json["conversation_memory"]
    assert memory["current_goal"] == "order_create"
    assert memory["current_topic"] == "حذاء"
    assert memory["selected_product_id"] == reloaded.metadata_json[
        "selected_product_id"
    ]
    assert memory["selected_variant_attributes"] == {
        "color": "black",
        "size": "42",
    }
    assert memory["pending_question"] == "CUSTOMER_DELIVERY_INFO"
    assert memory["pending_action"] == "collect_delivery_details"
    assert memory["active_draft_id"] == reloaded.active_draft_json["draft_id"]
    assert memory["customer_info"]["phone"] == "0550123456"
    assert memory["recent_image_understanding"] == [
        "حذاء أزرق ظاهر في الصورة."
    ]
    assert ConversationEngine._memory_for_agent(memory)["current_goal"] == (
        "order_create"
    )

    ConversationEngine._refresh_conversation_memory(
        db_session,
        reloaded,
        ConversationEngine._normalize_current_state(reloaded, store.id),
        "store_info",
    )
    assert reloaded.metadata_json["conversation_memory"]["current_topic"] == (
        "store_info"
    )
    assert reloaded.metadata_json["conversation_memory"]["pending_action"] == (
        "collect_delivery_details"
    )
    assert reloaded.active_draft_json["items"] == [
        {"product_name": "حذاء", "quantity": 1}
    ]


def test_product_photo_request_requires_an_explicit_image_request():
    assert is_product_image_request("ممكن صور المنتج")
    assert is_product_image_request("أرسل لي صورة العباية")
    assert is_product_image_request("send me a photo")
    assert not is_product_image_request("قداش سعر المنتج؟")


def test_facebook_adapter_normalizes_image_only_messages():
    event = FacebookAdapter().normalize_inbound_event(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "customer-psid"},
                            "message": {
                                "mid": "image-message-id",
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
                    ]
                }
            ]
        }
    )

    assert event.message_text == ""
    assert event.attachments[0].type == "image"
    assert event.attachments[0].url == "https://lookaside.fbsbx.com/image"


def test_webhook_payload_redaction_removes_message_text_tokens_and_urls():
    redacted = _redact_webhook_payload(
        {
            "access_token": "private-token",
            "entry": [
                {
                    "messaging": [
                        {
                            "message": {
                                "text": "private customer text",
                                "attachments": [
                                    {
                                        "payload": {
                                            "url": "https://private.example/signed"
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }
    )

    rendered = str(redacted)
    assert "private-token" not in rendered
    assert "private customer text" not in rendered
    assert "https://private.example/signed" not in rendered
