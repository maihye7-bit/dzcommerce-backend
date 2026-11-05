import io
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.store import Store
from app.services import inbound_attachments, messenger_media, product_image_storage
from app.services.inbound_attachments import InboundAttachmentError
from app.services.messenger_media import MessengerDeliveryResult
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
    monkeypatch.setattr(messenger_media, "FACEBOOK_PAGE_ACCESS_TOKEN", "test-token")
    captured = {}
    real_async_client = httpx.AsyncClient

    def handle(request):
        captured["url"] = request.url
        captured["payload"] = request.read().decode()
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
    )

    assert result.delivered is True
    assert result.status_code == 200
    assert captured["url"].host == "graph.facebook.com"
    assert '"type":"image"' in captured["payload"]
    assert '"url":"https://shop.example.test/api/product-images/image-id/content"' in captured[
        "payload"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False])
async def test_send_product_image_tool_is_contextual_and_falls_back_on_api_failure(
    db_session, monkeypatch, delivered
):
    store = Store(name="Messenger image store", slug=f"messenger-image-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(
        store_id=store.id,
        name="Messenger customer",
        phone="customer-psid",
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
        metadata_json={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(product.id),
            "selected_product_name": product.name,
        },
    )
    db_session.add(conversation)
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
    send_image = AsyncMock(
        return_value=MessengerDeliveryResult(
            delivered=delivered,
            status_code=200 if delivered else 400,
            failure_code=None if delivered else "graph_api_rejected",
        )
    )
    monkeypatch.setattr(
        "app.agent.tools.send_product_image.send_messenger_image",
        send_image,
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
    )

    assert response["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:send_product_image"
    )
    assert response["response"] == (
        "تفضل، أرسلت لك صورة المنتج."
        if delivered
        else "تعذر إرسال صورة المنتج الآن. يمكنني مساعدتك بمعلوماته."
    )
    send_image.assert_awaited_once_with(
        "customer-psid",
        f"https://shop.example.test{image.image_url}",
    )


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
