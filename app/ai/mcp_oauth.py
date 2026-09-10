"""OAuth discovery and token helpers for remote MCP servers."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


class OAuthDiscoveryError(RuntimeError):
    """Raised when an MCP server advertises OAuth but discovery is invalid."""


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def canonical_resource_uri(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("MCP URL must be an absolute http(s) URL")
    path = parts.path or ""
    if path == "/":
        path = ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def protected_resource_metadata_urls(mcp_url: str) -> list[str]:
    """Return MCP well-known URLs in the order required by the current spec."""
    parts = urlsplit(canonical_resource_uri(mcp_url))
    root = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.strip("/")
    urls = []
    if path:
        urls.append(f"{root}/.well-known/oauth-protected-resource/{path}")
    urls.append(f"{root}/.well-known/oauth-protected-resource")
    return urls


def authorization_server_metadata_urls(issuer: str) -> list[str]:
    """Build RFC8414/OIDC discovery URLs in MCP priority order."""
    parts = urlsplit(issuer.rstrip("/"))
    if parts.scheme != "https" or not parts.netloc:
        raise OAuthDiscoveryError("OAuth authorization server issuer must use HTTPS")
    root = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.strip("/")
    if path:
        return [
            f"{root}/.well-known/oauth-authorization-server/{path}",
            f"{root}/.well-known/openid-configuration/{path}",
            f"{root}/{path}/.well-known/openid-configuration",
        ]
    return [
        f"{root}/.well-known/oauth-authorization-server",
        f"{root}/.well-known/openid-configuration",
    ]


def _challenge_param(header: str, name: str) -> str:
    match = re.search(rf"(?:^|[,\s]){re.escape(name)}=(?:\"([^\"]*)\"|([^,\s]+))", header, re.I)
    if not match:
        return ""
    return match.group(1) or match.group(2) or ""


def build_authorization_url(
    authorization_url: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = "",
    resource: str = "",
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
    if resource:
        query["resource"] = resource
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


async def _get_json(session, url: str) -> dict | None:
    try:
        async with session.get(url, headers={"Accept": "application/json"}, allow_redirects=True) as response:
            if response.status != 200:
                return None
            if int(response.headers.get("Content-Length", "0") or 0) > 1_000_000:
                return None
            text = await response.text()
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


async def _register_dynamic_client(
    session,
    registration_endpoint: str,
    redirect_uri: str,
) -> dict:
    payload = {
        "client_name": "Starchatter Telegram Bot",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    async with session.post(
        registration_endpoint,
        json=payload,
        headers={"Accept": "application/json"},
    ) as response:
        body = await response.text()
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OAuthDiscoveryError("Dynamic client registration returned invalid JSON") from exc
        if response.status >= 400:
            detail = result.get("error_description") or result.get("error") or response.reason
            raise OAuthDiscoveryError(f"Dynamic client registration failed ({response.status}): {detail}")
        client_id = str(result.get("client_id") or "").strip()
        if not client_id:
            raise OAuthDiscoveryError("Dynamic client registration did not return client_id")
        return result


async def discover_mcp_oauth(
    mcp_url: str,
    *,
    redirect_uri: str,
    client_metadata_uri: str,
) -> dict | None:
    """Discover MCP OAuth endpoints and client registration automatically.

    Returns None when no standard MCP OAuth metadata can be found. If OAuth
    metadata is found but invalid, raises OAuthDiscoveryError.
    """
    import aiohttp

    resource = canonical_resource_uri(mcp_url)
    timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_read=5)
    challenge_metadata_url = ""
    challenge_scope = ""

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # First contact the MCP resource without a token. A conforming protected
        # server returns 401 with resource_metadata in WWW-Authenticate.
        try:
            async with session.get(
                resource,
                headers={"Accept": "application/json, text/event-stream"},
                allow_redirects=True,
            ) as response:
                if response.status == 401:
                    challenge = response.headers.get("WWW-Authenticate", "")
                    challenge_metadata_url = _challenge_param(challenge, "resource_metadata")
                    challenge_scope = _challenge_param(challenge, "scope")
                    if challenge_metadata_url:
                        challenge_metadata_url = urljoin(resource, challenge_metadata_url)
        except Exception:
            # Well-known discovery can still succeed even if the endpoint does
            # not accept GET or closes an SSE connection immediately.
            pass

        metadata_candidates = []
        if challenge_metadata_url:
            metadata_candidates.append(challenge_metadata_url)
        metadata_candidates.extend(protected_resource_metadata_urls(resource))

        protected = None
        protected_url = ""
        seen = set()
        for candidate in metadata_candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            payload = await _get_json(session, candidate)
            if payload and isinstance(payload.get("authorization_servers"), list) and payload["authorization_servers"]:
                protected = payload
                protected_url = candidate
                break

        if not protected:
            return None

        advertised_resource = str(protected.get("resource") or "").strip()
        if not advertised_resource:
            raise OAuthDiscoveryError("Protected Resource Metadata is missing resource")
        if urlsplit(advertised_resource).scheme != "https":
            raise OAuthDiscoveryError("Protected Resource Metadata resource must use HTTPS")

        authorization_servers = protected.get("authorization_servers") or []
        issuer = str(authorization_servers[0] or "").strip()
        if not issuer:
            raise OAuthDiscoveryError("Protected Resource Metadata has no authorization server")

        auth_metadata = None
        auth_metadata_url = ""
        for candidate in authorization_server_metadata_urls(issuer):
            payload = await _get_json(session, candidate)
            if not payload:
                continue
            metadata_issuer = str(payload.get("issuer") or "")
            if metadata_issuer != issuer:
                continue
            if payload.get("authorization_endpoint") and payload.get("token_endpoint"):
                auth_metadata = payload
                auth_metadata_url = candidate
                break

        if not auth_metadata:
            raise OAuthDiscoveryError("Could not discover OAuth authorization server metadata")

        pkce_methods = auth_metadata.get("code_challenge_methods_supported")
        if not isinstance(pkce_methods, list) or "S256" not in pkce_methods:
            raise OAuthDiscoveryError("OAuth authorization server does not advertise PKCE S256 support")

        authorization_url = str(auth_metadata["authorization_endpoint"])
        token_url = str(auth_metadata["token_endpoint"])
        if urlsplit(authorization_url).scheme != "https" or urlsplit(token_url).scheme != "https":
            raise OAuthDiscoveryError("OAuth authorization and token endpoints must use HTTPS")

        scope = challenge_scope
        if not scope:
            scopes_supported = protected.get("scopes_supported")
            if isinstance(scopes_supported, list):
                scope = " ".join(str(value) for value in scopes_supported if value)

        config = {
            "authorization_url": authorization_url,
            "token_url": token_url,
            "authorization_server": issuer,
            "authorization_metadata_url": auth_metadata_url,
            "resource_metadata_url": protected_url,
            "resource": advertised_resource or resource,
            "scope": scope,
            "discovered": True,
            "client_secret": "",
            "authorization_response_iss_parameter_supported": bool(
                auth_metadata.get("authorization_response_iss_parameter_supported")
            ),
        }

        if auth_metadata.get("client_id_metadata_document_supported") is True:
            config.update(
                {
                    "client_id": client_metadata_uri,
                    "client_registration": "client_metadata_document",
                    "token_endpoint_auth_method": "none",
                }
            )
            return config

        registration_endpoint = str(auth_metadata.get("registration_endpoint") or "").strip()
        if registration_endpoint and urlsplit(registration_endpoint).scheme == "https":
            try:
                registration = await _register_dynamic_client(session, registration_endpoint, redirect_uri)
                config.update(
                    {
                        "client_id": str(registration["client_id"]),
                        "client_secret": str(registration.get("client_secret") or ""),
                        "client_registration": "dynamic",
                        "token_endpoint_auth_method": str(
                            registration.get("token_endpoint_auth_method")
                            or ("client_secret_basic" if registration.get("client_secret") else "none")
                        ),
                    }
                )
                return config
            except OAuthDiscoveryError as exc:
                config["registration_error"] = str(exc)

        auth_methods = auth_metadata.get("token_endpoint_auth_methods_supported")
        manual_auth_method = "client_secret_basic"
        if isinstance(auth_methods, list):
            if "client_secret_basic" in auth_methods:
                manual_auth_method = "client_secret_basic"
            elif "client_secret_post" in auth_methods:
                manual_auth_method = "client_secret_post"
            elif "none" in auth_methods:
                manual_auth_method = "none"

        config.update(
            {
                "client_id": "",
                "client_registration": "manual",
                "token_endpoint_auth_method": manual_auth_method,
            }
        )
        return config


async def _token_request(
    token_url: str,
    data: dict[str, str],
    client_secret: str = "",
    auth_method: str = "",
) -> dict:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=20)
    client_id = data.get("client_id", "")
    method = auth_method or ("client_secret_basic" if client_secret else "none")
    auth = None
    request_data = dict(data)
    if client_id and client_secret and method == "client_secret_basic":
        auth = aiohttp.BasicAuth(client_id, client_secret)
    elif client_secret and method == "client_secret_post":
        request_data["client_secret"] = client_secret

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            token_url,
            data=request_data,
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
    resource = str(config.get("resource") or "")
    if resource:
        data["resource"] = resource
    payload = await _token_request(
        str(config.get("token_url") or ""),
        data,
        str(config.get("client_secret") or ""),
        str(config.get("token_endpoint_auth_method") or ""),
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
    resource = str(config.get("resource") or "")
    if resource:
        data["resource"] = resource

    payload = await _token_request(
        str(config.get("token_url") or ""),
        data,
        str(config.get("client_secret") or ""),
        str(config.get("token_endpoint_auth_method") or ""),
    )
    return _apply_token_payload(config, payload)
