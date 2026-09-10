"""Public OAuth callback route used by the MCP OAuth2 authorization flow.

This router is mounted by the companion Content API on serv00 so the public
HTTPS domain can receive OAuth authorization codes. The callback never stores
credentials in a public web directory; it writes a short-lived state/code file
under the system temp directory for the Telegram bot to consume.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()
_STATE_RE = re.compile(r"^[A-Za-z0-9_-]{20,200}$")


def _callback_dir() -> Path:
    return Path(tempfile.gettempdir()) / "starchatter-oauth"


@router.get("/oauth_callback.php", response_class=HTMLResponse, include_in_schema=False)
def mcp_oauth_callback(
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    if not _STATE_RE.fullmatch(state):
        return HTMLResponse("<h2>Invalid OAuth state.</h2>", status_code=400)

    payload = {
        "state": state,
        "code": code,
        "error": error,
        "error_description": error_description,
        "created_at": int(time.time()),
    }

    callback_dir = _callback_dir()
    callback_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    callback_file = callback_dir / f"{state}.json"
    callback_file.write_text(json.dumps(payload))
    callback_file.chmod(0o600)

    if error:
        detail = error_description or error
        return HTMLResponse(
            "<h2>OAuth authorization failed</h2>"
            f"<p>{_escape_html(detail)}</p>"
            "<p>You can return to Telegram now.</p>",
            status_code=400,
        )

    return HTMLResponse(
        "<h2>OAuth authorization received ✅</h2>"
        "<p>Return to Telegram and press <strong>Check Authorization</strong>.</p>"
    )


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
