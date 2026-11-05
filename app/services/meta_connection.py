"""Facebook Page credential verification using Meta Graph API."""

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v26.0"
REQUIRED_PAGE_PERMISSIONS = {"pages_messaging", "pages_manage_metadata"}


@dataclass(frozen=True)
class VerifiedFacebookPage:
    page_id: str
    page_name: str


class MetaConnectionError(Exception):
    def __init__(self, detail: str, status_code: int):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _redact_meta_error_value(value: object, secrets: tuple[str, ...]) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return None
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


async def verify_facebook_page(
    *,
    page_id: str,
    page_name: str,
    page_access_token: str,
) -> VerifiedFacebookPage:
    app_id = settings.META_APP_ID.strip()
    app_secret = settings.META_APP_SECRET.strip()
    if not app_id or not app_secret:
        raise MetaConnectionError(
            "Meta App credentials are not configured on the server.", 503
        )

    base_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    app_access_token = f"{app_id}|{app_secret}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            debug_response = await client.get(
                f"{base_url}/debug_token",
                params={
                    "input_token": page_access_token,
                    "access_token": app_access_token,
                },
            )
            if not debug_response.is_success:
                try:
                    error_response = debug_response.json()
                except (ValueError, TypeError):
                    error_response = None
                error_data = (
                    error_response.get("error")
                    if isinstance(error_response, dict)
                    else None
                )
                if not isinstance(error_data, dict):
                    error_data = {}
                redaction_secrets = (
                    page_access_token,
                    app_access_token,
                    app_secret,
                )
                log_fields = {
                    "http_status": debug_response.status_code,
                    "meta_error_code": _redact_meta_error_value(
                        error_data.get("code"), redaction_secrets
                    ),
                    "meta_error_subcode": _redact_meta_error_value(
                        error_data.get("error_subcode"), redaction_secrets
                    ),
                    "meta_error_type": _redact_meta_error_value(
                        error_data.get("type"), redaction_secrets
                    ),
                    "meta_error_message": _redact_meta_error_value(
                        error_data.get("message"), redaction_secrets
                    ),
                }
                logger.warning(
                    json.dumps(
                        {"event": "meta_page_token_debug_failed", **log_fields},
                        separators=(",", ":"),
                    ),
                    extra={"event": "meta_page_token_debug_failed", **log_fields},
                )
                if debug_response.status_code >= 500:
                    raise MetaConnectionError(
                        "Meta could not be reached to validate the Page Access Token.",
                        502,
                    )
                raise MetaConnectionError(
                    "Meta could not validate the supplied Page Access Token.", 422
                )
            debug_json = debug_response.json()
            debug_data = (
                debug_json.get("data") if isinstance(debug_json, dict) else None
            )
            if not isinstance(debug_data, dict):
                raise MetaConnectionError(
                    "Meta returned an invalid token verification response.", 502
                )
            if (
                debug_data.get("is_valid") is not True
                or str(debug_data.get("app_id") or "") != app_id
                or debug_data.get("type") != "PAGE"
            ):
                raise MetaConnectionError(
                    "The token must be a valid Page Access Token for this Meta App.",
                    422,
                )
            scopes = debug_data.get("scopes")
            granted_permissions = (
                {scope for scope in scopes if isinstance(scope, str)}
                if isinstance(scopes, list)
                else set()
            )
            missing_permissions = REQUIRED_PAGE_PERMISSIONS - granted_permissions
            if missing_permissions:
                raise MetaConnectionError(
                    "The Page Access Token is missing required Messenger permissions.",
                    422,
                )

            page_response = await client.get(
                f"{base_url}/{page_id}",
                params={"fields": "id,name", "access_token": page_access_token},
            )
            if not page_response.is_success:
                logger.warning(
                    "meta_page_details_check_failed status=%d",
                    page_response.status_code,
                )
                raise MetaConnectionError(
                    "Meta could not read the requested Facebook Page.", 422
                )
            page_data = page_response.json()
    except MetaConnectionError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning(
            "meta_page_verification_unavailable error_type=%s",
            type(exc).__name__,
        )
        raise MetaConnectionError(
            "Meta could not be reached to verify the Facebook Page.", 502
        ) from exc

    if not isinstance(page_data, dict):
        raise MetaConnectionError(
            "Meta returned an invalid Facebook Page response.", 502
        )
    returned_page_id = str(page_data.get("id") or "")
    returned_page_name = page_data.get("name")
    if returned_page_id != page_id:
        raise MetaConnectionError(
            "The supplied Page ID does not match the verified Facebook Page.", 422
        )
    if (
        not isinstance(returned_page_name, str)
        or returned_page_name.strip().casefold() != page_name.strip().casefold()
    ):
        raise MetaConnectionError(
            "The supplied Page name does not match the verified Facebook Page.",
            422,
        )

    return VerifiedFacebookPage(
        page_id=returned_page_id,
        page_name=returned_page_name.strip(),
    )
