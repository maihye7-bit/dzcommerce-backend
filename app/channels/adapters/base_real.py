"""
Base class for real platform adapters.
Provides shared HTTP client, token management, and error handling.
"""

from typing import Optional

import httpx


class BaseRealAdapter:
    """Shared infrastructure for all real Meta/WhatsApp adapters."""

    GRAPH_API_VERSION = "v25.0"
    GRAPH_API_BASE = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: Optional[str] = None,
        external_account_id: Optional[str] = None,
    ):
        self._access_token = access_token
        self._external_account_id = external_account_id
        self._client = httpx.AsyncClient(timeout=30.0)

    def require_account_credentials(self, external_account_id: str) -> str:
        if not self._access_token or not self._access_token.strip():
            raise RuntimeError("An explicit Meta access token is required for sending")
        if (
            not self._external_account_id
            or not self._external_account_id.strip()
            or self._external_account_id != external_account_id
        ):
            raise RuntimeError(
                "The Meta access token is not bound to the requested account"
            )
        return self._access_token

    @property
    def graph_url(self) -> str:
        return f"{self.GRAPH_API_BASE}/{self.GRAPH_API_VERSION}"

    async def _post(self, endpoint: str, json_data: dict) -> dict:
        """Make authenticated POST request to Graph API."""
        access_token = self.require_account_credentials(
            self._external_account_id or ""
        )
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await self._client.post(url, json=json_data, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make authenticated GET request to Graph API."""
        access_token = self.require_account_credentials(
            self._external_account_id or ""
        )
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
