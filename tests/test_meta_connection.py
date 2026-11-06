import json
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api import stores
from app.config import settings
from app.core.deps import get_current_store_owner
from app.models.channel_account import ChannelAccount
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.store_meta_token import StoreMetaToken
from app.schemas.store_meta_connection import StoreMetaConnectionRequest
from app.services import meta_connection
from app.services.meta_token_security import decrypt_meta_token, encrypt_meta_token
from app.services.outbound_delivery import resolve_meta_access_token


class MockMetaResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._body = body

    def json(self):
        return self._body


class MockMetaClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, *, params):
        self.requests.append((url, params))
        return next(self.responses)


def _verified_responses(
    *,
    scopes=None,
    debug_status=200,
    page_status=200,
    page_id="page-123",
    page_name="My Shop",
    token_type="PAGE",
    app_id="test-meta-app",
):
    debug = MockMetaResponse(
        debug_status,
        {
            "data": {
                "is_valid": True,
                "app_id": app_id,
                "type": token_type,
                "scopes": scopes
                if scopes is not None
                else ["pages_messaging", "pages_manage_metadata"],
            }
        },
    )
    page = MockMetaResponse(
        page_status,
        {"id": page_id, "name": page_name},
    )
    return [debug, page]


def _payload(
    *,
    page_id="page-123",
    page_name="My Shop",
    access_token="page-access-token-that-must-not-leak",
):
    return StoreMetaConnectionRequest(
        pageId=page_id,
        pageName=page_name,
        pageAccessToken=access_token,
    )


def _set_credentials(monkeypatch, app_id="test-meta-app"):
    monkeypatch.setattr(settings, "META_APP_ID", app_id)
    monkeypatch.setattr(settings, "META_APP_SECRET", "test-meta-app-secret")
    monkeypatch.setattr(
        settings,
        "SOCIAL_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )


def _set_responses(monkeypatch, responses):
    client = MockMetaClient(responses)
    monkeypatch.setattr(
        meta_connection.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    return client


def test_meta_connection_request_accepts_snake_case_fields():
    request = StoreMetaConnectionRequest.model_validate(
        {
            "page_name": "DzCommerce Page",
            "page_id": "787421191421688",
            "page_access_token": "page-access-token-that-must-not-leak",
        }
    )

    assert request.page_name == "DzCommerce Page"
    assert request.page_id == "787421191421688"


def test_post_accepts_frontend_json_and_preserves_other_store(
    client, db_session, monkeypatch, caplog, recwarn
):
    app_id = "1656044335910188"
    _set_credentials(monkeypatch, app_id=app_id)
    target_store = Store(name="Meta connect", slug=f"meta-connect-{uuid.uuid4()}")
    other_store = Store(name="Other Meta", slug=f"other-meta-{uuid.uuid4()}")
    db_session.add_all([target_store, other_store])
    db_session.flush()
    existing_account = ChannelAccount(
        store_id=target_store.id,
        channel="facebook",
        external_account_id="787421191421688",
        external_account_name="Previous Page Name",
        is_active=False,
    )
    existing_token = StoreMetaToken(
        store_id=target_store.id,
        page_id="787421191421688",
        page_name="Previous Page Name",
        access_token=encrypt_meta_token("previous-target-token"),
    )
    other_account = ChannelAccount(
        store_id=other_store.id,
        channel="facebook",
        external_account_id="other-page-id",
        external_account_name="Other Page",
        is_active=True,
    )
    other_token = StoreMetaToken(
        store_id=other_store.id,
        page_id="other-page-id",
        page_name="Other Page",
        access_token=encrypt_meta_token("other-store-token"),
    )
    db_session.add_all([existing_account, existing_token, other_account, other_token])
    db_session.commit()

    client.app.dependency_overrides[get_current_store_owner] = lambda: StoreUser(
        store_id=target_store.id,
        user_id=uuid.uuid4(),
        role=StoreRole.OWNER,
    )
    meta_client = _set_responses(
        monkeypatch,
        _verified_responses(
            page_id="787421191421688",
            page_name="DzCommerce Page",
            app_id=app_id,
        ),
    )
    page_access_token = "page-access-token-that-must-not-leak"
    try:
        response = client.post(
            f"/api/stores/{target_store.id}/meta-connection",
            json={
                "pageName": "DzCommerce Page",
                "pageId": "787421191421688",
                "pageAccessToken": page_access_token,
            },
        )
    finally:
        client.app.dependency_overrides.pop(get_current_store_owner, None)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["connected"] is True
    assert response_data["pageId"] == "787421191421688"
    assert response_data["pageName"] == "DzCommerce Page"
    assert meta_client.requests[0][1]["input_token"] == page_access_token
    assert meta_client.requests[0][1]["access_token"] == (
        f"{app_id}|test-meta-app-secret"
    )
    assert meta_client.requests[1][0].endswith("/787421191421688")
    assert meta_client.requests[1][1] == {
        "fields": "id,name",
        "access_token": page_access_token,
    }
    db_session.refresh(existing_account)
    db_session.refresh(existing_token)
    db_session.refresh(other_account)
    db_session.refresh(other_token)
    assert existing_account.is_active is True
    assert existing_account.external_account_name == "DzCommerce Page"
    assert db_session.query(ChannelAccount).filter_by(
        store_id=target_store.id, channel="facebook"
    ).count() == 1
    assert db_session.query(StoreMetaToken).filter_by(store_id=target_store.id).count() == 1
    assert decrypt_meta_token(existing_token.access_token) == page_access_token
    assert other_account.is_active is True
    assert other_account.external_account_name == "Other Page"
    assert decrypt_meta_token(other_token.access_token) == "other-store-token"
    assert page_access_token not in response.text
    assert page_access_token not in caplog.text
    assert not [
        warning
        for warning in recwarn
        if "UnsupportedFieldAttributeWarning" in warning.category.__name__
    ]


@pytest.mark.asyncio
async def test_valid_page_token_and_matching_page_are_saved_atomically(
    db_session, monkeypatch, caplog
):
    _set_credentials(monkeypatch)
    client = _set_responses(monkeypatch, _verified_responses())
    store = Store(name="Meta connect", slug=f"meta-connect-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    plaintext_token = "page-access-token-that-must-not-leak"

    response = await stores.connect_store_meta(
        store_id=store.id,
        payload=_payload(access_token=plaintext_token),
        membership=None,
        db=db_session,
    )

    account = (
        db_session.query(ChannelAccount)
        .filter_by(store_id=store.id, channel="facebook")
        .one()
    )
    stored_token = (
        db_session.query(StoreMetaToken).filter_by(store_id=store.id).one()
    )
    assert account.external_account_id == "page-123"
    assert account.external_account_name == "My Shop"
    assert account.is_active is True
    assert stored_token.page_id == "page-123"
    assert stored_token.access_token != plaintext_token
    assert decrypt_meta_token(stored_token.access_token) == plaintext_token
    assert response.connected and response.verified
    assert plaintext_token not in str(response.model_dump())
    assert plaintext_token not in caplog.text
    assert client.requests[0][1]["input_token"] == plaintext_token


@pytest.mark.parametrize(
    ("responses", "payload", "expected_status"),
    [
        (
            [
                MockMetaResponse(
                    200,
                    {
                        "data": {
                            "is_valid": False,
                            "app_id": "test-meta-app",
                            "scopes": ["pages_messaging", "pages_manage_metadata"],
                        }
                    },
                )
            ],
            _payload(),
            422,
        ),
        (
            _verified_responses(),
            _payload(page_id="wrong-page"),
            422,
        ),
        (
            _verified_responses(scopes=["pages_show_list"]),
            _payload(),
            422,
        ),
        (
            _verified_responses(token_type="USER"),
            _payload(),
            422,
        ),
        (
            [MockMetaResponse(503, {"error": {"message": "unavailable"}})],
            _payload(),
            502,
        ),
        (
            [
                MockMetaResponse(
                    400,
                    {
                        "error": {
                            "code": 190,
                            "type": "OAuthException",
                            "message": "Invalid token",
                        }
                    },
                )
            ],
            _payload(),
            422,
        ),
    ],
)
@pytest.mark.asyncio
async def test_failed_meta_verification_never_persists_partial_connection(
    db_session, monkeypatch, responses, payload, expected_status
):
    _set_credentials(monkeypatch)
    _set_responses(monkeypatch, responses)
    store = Store(name="Meta failed", slug=f"meta-failed-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        await stores.connect_store_meta(
            store_id=store.id,
            payload=payload,
            membership=None,
            db=db_session,
        )

    assert error.value.status_code == expected_status
    assert db_session.query(ChannelAccount).filter_by(store_id=store.id).count() == 0
    assert db_session.query(StoreMetaToken).filter_by(store_id=store.id).count() == 0


@pytest.mark.asyncio
async def test_debug_token_error_details_are_logged_without_credentials(
    monkeypatch, caplog
):
    _set_credentials(monkeypatch)
    page_token = "page-token-must-not-be-logged"
    app_secret = "test-meta-app-secret"
    error_message = (
        f"Invalid token {page_token}; app token test-meta-app|{app_secret}"
    )
    _set_responses(
        monkeypatch,
        [
            MockMetaResponse(
                400,
                {
                    "error": {
                        "code": 190,
                        "error_subcode": 1234567,
                        "type": "OAuthException",
                        "message": error_message,
                    }
                },
            )
        ],
    )

    with pytest.raises(meta_connection.MetaConnectionError):
        await meta_connection.verify_facebook_page(
            page_id="page-123",
            page_name="My Shop",
            page_access_token=page_token,
        )

    record = next(
        record
        for record in caplog.records
        if record.event == "meta_page_token_debug_failed"
    )
    logged = json.loads(record.message)
    assert logged["event"] == "meta_page_token_debug_failed"
    assert logged["http_status"] == 400
    assert logged["meta_error_code"] == 190
    assert logged["meta_error_subcode"] == 1234567
    assert logged["meta_error_type"] == "OAuthException"
    assert logged["meta_error_message"] == (
        "Invalid token [REDACTED]; app token [REDACTED]"
    )
    assert record.http_status == 400
    assert record.meta_error_code == 190
    assert record.meta_error_subcode == 1234567
    assert record.meta_error_type == "OAuthException"
    assert record.meta_error_message == (
        "Invalid token [REDACTED]; app token [REDACTED]"
    )
    assert page_token not in caplog.text
    assert app_secret not in caplog.text


@pytest.mark.asyncio
async def test_page_already_linked_to_another_store_is_rejected(
    db_session, monkeypatch
):
    _set_credentials(monkeypatch)
    _set_responses(monkeypatch, _verified_responses())
    owner_store = Store(name="Page owner", slug=f"page-owner-{uuid.uuid4()}")
    requested_store = Store(name="Other store", slug=f"other-store-{uuid.uuid4()}")
    db_session.add_all([owner_store, requested_store])
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=owner_store.id,
            channel="facebook",
            external_account_id="page-123",
            external_account_name="My Shop",
            is_active=True,
        )
    )
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        await stores.connect_store_meta(
            store_id=requested_store.id,
            payload=_payload(),
            membership=None,
            db=db_session,
        )

    assert error.value.status_code == 409
    assert db_session.query(StoreMetaToken).filter_by(store_id=requested_store.id).count() == 0
    assert db_session.query(ChannelAccount).filter_by(store_id=requested_store.id).count() == 0


def test_facebook_page_link_is_unique_across_stores_in_the_database(db_session):
    first_store = Store(name="First page owner", slug=f"first-owner-{uuid.uuid4()}")
    second_store = Store(name="Second page owner", slug=f"second-owner-{uuid.uuid4()}")
    db_session.add_all([first_store, second_store])
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=first_store.id,
            channel="facebook",
            external_account_id="globally-unique-page",
            is_active=True,
        )
    )
    db_session.commit()
    db_session.add(
        ChannelAccount(
            store_id=second_store.id,
            channel="facebook",
            external_account_id="globally-unique-page",
            is_active=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert (
        db_session.query(ChannelAccount)
        .filter_by(channel="facebook", external_account_id="globally-unique-page")
        .count()
        == 1
    )


@pytest.mark.asyncio
async def test_database_save_failure_rolls_back_both_connection_rows(
    db_session, monkeypatch
):
    _set_credentials(monkeypatch)
    _set_responses(monkeypatch, _verified_responses())
    store = Store(name="Meta save fails", slug=f"meta-save-fails-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()

    def fail_commit():
        raise SQLAlchemyError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(HTTPException) as error:
        await stores.connect_store_meta(
            store_id=store.id,
            payload=_payload(),
            membership=None,
            db=db_session,
        )
    assert error.value.status_code == 500
    assert db_session.query(ChannelAccount).filter_by(store_id=store.id).count() == 0
    assert db_session.query(StoreMetaToken).filter_by(store_id=store.id).count() == 0


@pytest.mark.asyncio
async def test_connect_does_not_replace_a_different_instagram_token(
    db_session, monkeypatch
):
    _set_credentials(monkeypatch)
    _set_responses(monkeypatch, _verified_responses())
    store = Store(name="Existing Instagram", slug=f"existing-ig-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    db_session.add(
        StoreMetaToken(
            store_id=store.id,
            page_id="old-facebook-page",
            page_name="Old Facebook Page",
            instagram_page_id="instagram-account",
            access_token=encrypt_meta_token("existing-instagram-token"),
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        await stores.connect_store_meta(
            store_id=store.id,
            payload=_payload(),
            membership=None,
            db=db_session,
        )

    assert error.value.status_code == 409
    saved = db_session.query(StoreMetaToken).filter_by(store_id=store.id).one()
    assert decrypt_meta_token(saved.access_token) == "existing-instagram-token"
    assert db_session.query(ChannelAccount).filter_by(store_id=store.id).count() == 0


def test_disconnect_keeps_shared_credential_for_existing_instagram_link(
    db_session, monkeypatch
):
    _set_credentials(monkeypatch)
    store = Store(name="Shared Meta credentials", slug=f"shared-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    db_session.add(
        ChannelAccount(
            store_id=store.id,
            channel="facebook",
            external_account_id="facebook-page",
            is_active=True,
        )
    )
    db_session.add(
        StoreMetaToken(
            store_id=store.id,
            page_id="facebook-page",
            page_name="Facebook Page",
            instagram_page_id="instagram-account",
            access_token=encrypt_meta_token("shared-page-token"),
        )
    )
    db_session.commit()

    response = stores.disconnect_store_meta(
        store_id=store.id,
        membership=None,
        db=db_session,
    )

    assert response.connected is False
    assert (
        db_session.query(ChannelAccount)
        .filter_by(store_id=store.id, channel="facebook", is_active=True)
        .count()
        == 0
    )
    assert (
        db_session.query(StoreMetaToken)
        .filter_by(store_id=store.id, instagram_page_id="instagram-account")
        .count()
        == 1
    )
    assert (
        resolve_meta_access_token(
            db_session,
            store_id=store.id,
            channel="facebook",
            external_account_id="facebook-page",
        )
        is None
    )
    assert (
        resolve_meta_access_token(
            db_session,
            store_id=store.id,
            channel="instagram",
            external_account_id="instagram-account",
        )
        == "shared-page-token"
    )


@pytest.mark.asyncio
async def test_page_name_must_match_and_token_is_never_returned_or_logged(
    db_session, monkeypatch, caplog
):
    _set_credentials(monkeypatch)
    _set_responses(monkeypatch, _verified_responses())
    store = Store(name="Meta name mismatch", slug=f"meta-name-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        await stores.connect_store_meta(
            store_id=store.id,
            payload=_payload(page_name="Another Page"),
            membership=None,
            db=db_session,
        )

    assert error.value.status_code == 422
    assert "page-access-token-that-must-not-leak" not in caplog.text
    assert db_session.query(StoreMetaToken).filter_by(store_id=store.id).count() == 0
