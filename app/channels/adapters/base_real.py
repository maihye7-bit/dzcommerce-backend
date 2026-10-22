"""
Base class for real platform adapters.
Provides shared HTTP client, token management, and error handling.
"""

import os
from typing import Optional

import httpx


class BaseRealAdapter:
    """Shared infrastructure for all real Meta/WhatsApp adapters."""

    GRAPH_API_VERSION = "v25.0"
    GRAPH_API_BASE = "https://graph.facebook.com"

    def __init__(self, access_token: Optional[str] = None):
        self._access_token = access_token or os.environ.get("META_ACCESS_TOKEN", "")
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def graph_url(self) -> str:
        return f"{self.GRAPH_API_BASE}/{self.GRAPH_API_VERSION}"

    async def _post(self, endpoint: str, json_data: dict) -> dict:
        """Make authenticated POST request to Graph API."""
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = await self._client.post(url, json=json_data, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make authenticated GET request to Graph API."""
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
