"""OAuth helpers for remote MCP servers."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qsl, parse_qs, urlencode, urlsplit, urlunsplit



def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    authorization_url: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = "",
) -> str:
    parts = urlsplit(authorization_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    if scope:
        query["scope"] = scope
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _decode_token_payload(text: str) -> dict:
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        parsed = parse_qs(text, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items() if values}


def _apply_token_payload(config: dict, payload: dict) -> dict:
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("OAuth token response did not contain access_token")

    updated = dict(config)
    updated["access_token"] = str(token)
    updated["token_type"] = str(payload.get("token_type") or "Bearer")
    if payload.get("refresh_token"):
        updated["refresh_token"] = str(payload["refresh_token"])
    if payload.get("scope"):
        updated["granted_scope"] = str(payload["scope"])

    try:
        expires_in = int(payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if expires_in > 0:
        updated["expires_at"] = int(time.time()) + max(1, expires_in - 30)
    else:
        updated.pop("expires_at", None)
    return updated


async def _token_request(token_url: str, data: dict[str, str], client_secret: str = "") -> dict:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=20)
    client_id = data.get("client_id", "")
    auth = aiohttp.BasicAuth(client_id, client_secret) if client_id and client_secret else None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            token_url,
            data=data,
            auth=auth,
            headers={"Accept": "application/json"},
        ) as response:
            body = await response.text()
            payload = _decode_token_payload(body)
            if response.status >= 400:
                detail = payload.get("error_description") or payload.get("error") or response.reason
                raise RuntimeError(f"OAuth token request failed ({response.status}): {detail}")
            return payload


async def exchange_authorization_code(
    config: dict,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": str(config.get("client_id") or ""),
        "code_verifier": code_verifier,
    }
    payload = await _token_request(
        str(config.get("token_url") or ""),
        data,
        str(config.get("client_secret") or ""),
    )
    return _apply_token_payload(config, payload)


async def refresh_access_token(config: dict) -> dict:
    refresh_token = str(config.get("refresh_token") or "")
    if not refresh_token:
        raise RuntimeError("OAuth access token expired and no refresh_token is available")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": str(config.get("client_id") or ""),
    }
    scope = str(config.get("scope") or "")
    if scope:
        data["scope"] = scope

    payload = await _token_request(
        str(config.get("token_url") or ""),
        data,
        str(config.get("client_secret") or ""),
    )
    return _apply_token_payload(config, payload)
