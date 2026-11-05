import pytest

from app.channels.adapters.base_real import BaseRealAdapter
from app.channels.adapters.facebook_adapter import FacebookAdapter
from app.channels.adapters.instagram_adapter import InstagramAdapter
from app.channels.router import ChannelRouter
from app.schemas.channel_events import OutboundMessage


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message_id": "sent-message"}


class FakeClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, *, json, headers):
        self.calls.append((url, json, headers))
        return FakeResponse()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_router_refuses_global_token_without_account_binding(monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "global-token")
    adapter = FacebookAdapter()
    await adapter.close()
    client = FakeClient()
    adapter._client = client
    router = ChannelRouter()
    router.register(adapter)

    with pytest.raises(RuntimeError, match="explicit Meta access token"):
        await router.send(
            OutboundMessage(
                channel="facebook",
                recipient_external_id="recipient",
                text="Hello",
                metadata={"page_id": "page-1"},
            )
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_facebook_adapter_rejects_token_bound_to_another_page():
    adapter = FacebookAdapter(
        access_token="page-one-token",
        external_account_id="page-1",
    )
    await adapter.close()
    client = FakeClient()
    adapter._client = client

    with pytest.raises(RuntimeError, match="not bound to the requested account"):
        await adapter.send_message(
            OutboundMessage(
                channel="facebook",
                recipient_external_id="recipient",
                text="Hello",
                metadata={"page_id": "page-2"},
            )
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_router_sends_with_explicitly_account_bound_token():
    adapter = FacebookAdapter(
        access_token="page-one-token",
        external_account_id="page-1",
    )
    await adapter.close()
    client = FakeClient()
    adapter._client = client
    router = ChannelRouter()
    router.register(adapter)

    result = await router.send(
        OutboundMessage(
            channel="facebook",
            recipient_external_id="recipient",
            text="Hello",
            metadata={"page_id": "page-1"},
        )
    )

    assert result == {"message_id": "sent-message"}
    assert client.calls[0][0].endswith("/page-1/messages")
    assert client.calls[0][2]["Authorization"] == "Bearer page-one-token"


@pytest.mark.asyncio
async def test_instagram_adapter_requires_matching_account_binding():
    adapter = InstagramAdapter(
        access_token="instagram-token",
        external_account_id="ig-account-1",
    )
    await adapter.close()
    client = FakeClient()
    adapter._client = client

    with pytest.raises(RuntimeError, match="not bound to the requested account"):
        await adapter.send_message(
            OutboundMessage(
                channel="instagram",
                recipient_external_id="recipient",
                text="Hello",
                metadata={"ig_account_id": "ig-account-2"},
            )
        )

    assert client.calls == []


def test_base_real_adapter_does_not_read_environment_token(monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "global-token")
    adapter = BaseRealAdapter()
    try:
        assert adapter._access_token is None
    finally:
        import asyncio

        asyncio.run(adapter.close())
