"""Tests for Phase 3 agent tools + tenant isolation."""
import pytest
from tests.helpers import register_and_get_token, auth_headers, get_first_store_id


class TestSearchProductsTool:
    def test_search_returns_products_for_own_store(self, client):
        token = register_and_get_token(client, "agent_search@example.com", store_name="Agent Search Store")
        store_id = get_first_store_id(client, token)
        headers = auth_headers(token)

        resp = client.post(f"/api/stores/{store_id}/products", json={
            "name": "Samsung Galaxy A56", "price": "45000.00", "sku": "SAM-A56",
        }, headers=headers)
        assert resp.status_code == 201

        resp = client.post("/api/agent/chat", json={
            "store_id": store_id, "message": "search Samsung", "channel": "api",
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "conversation_id" in data
        assert data["handoff"] is False

    def test_search_cannot_access_other_store(self, client):
        token_a = register_and_get_token(client, "agent_iso_a@example.com", store_name="Store ISO A")
        token_b = register_and_get_token(client, "agent_iso_b@example.com", store_name="Store ISO B")
        store_a = get_first_store_id(client, token_a)

        resp = client.post("/api/agent/chat", json={
            "store_id": store_a, "message": "search products", "channel": "api",
        }, headers=auth_headers(token_b))
        assert resp.status_code == 404


class TestHandoffToHuman:
    def test_handoff_creates_record(self, client):
        token = register_and_get_token(client, "agent_handoff@example.com", store_name="Handoff Store")
        store_id = get_first_store_id(client, token)
        headers = auth_headers(token)

        resp = client.post("/api/agent/chat", json={
            "store_id": store_id, "message": "I want to speak to a human", "channel": "api",
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["handoff"] is True


class TestAgentChatValidation:
    def test_chat_requires_auth(self, client):
        resp = client.post("/api/agent/chat", json={
            "store_id": "00000000-0000-0000-0000-000000000000", "message": "test",
        })
        assert resp.status_code == 401

    def test_chat_rejects_invalid_store(self, client):
        token = register_and_get_token(client, "agent_invalid@example.com", store_name="Invalid Store")
        headers = auth_headers(token)
        resp = client.post("/api/agent/chat", json={
            "store_id": "00000000-0000-0000-0000-000000000000", "message": "test",
        }, headers=headers)
        assert resp.status_code == 404
