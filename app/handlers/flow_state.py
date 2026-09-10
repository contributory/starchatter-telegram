"""Shared registry of active admin input flows.

Some admin features are multi-step, button-driven "conversations" (for
example: Add MCP Server, Add/Edit Provider). While such a flow is waiting
for the admin to type a value, the message they send belongs to the flow and
must NOT be processed by the chatbot AI.

Flow handlers call :func:`start_flow` when they begin and :func:`end_flow`
when they finish (or are cancelled). The chatbot listener checks
:func:`is_in_flow` and skips AI processing for those messages.
"""

from typing import Dict, Optional

# user_id -> flow name (e.g. "mcp_add", "provider_add", "provider_edit")
_active_flows: Dict[int, str] = {}


def start_flow(user_id: int, flow: str) -> None:
    """Mark ``user_id`` as being inside the named input flow."""
    _active_flows[user_id] = flow


def end_flow(user_id: int) -> None:
    """Clear the active flow for ``user_id`` (finished or cancelled)."""
    _active_flows.pop(user_id, None)


def get_flow(user_id: int) -> Optional[str]:
    """Return the active flow name for ``user_id``, or None."""
    return _active_flows.get(user_id)


def is_in_flow(user_id: int) -> bool:
    """True if ``user_id`` is currently inside an admin input flow."""
    return user_id in _active_flows
