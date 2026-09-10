"""MCP server callback handlers - full button-based management."""

import json
import secrets
import tempfile
from pathlib import Path

from pyrogram import Client, enums, filters, types

from app.ai.mcp_oauth import build_authorization_url, create_pkce_pair, exchange_authorization_code
from app.config import MCP_OAUTH_REDIRECT_URI
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import MCPServer
from app.handlers.owner import is_user_owner
from app.handlers import flow_state
from app.handlers.pagination import ITEMS_PER_PAGE, create_providers_keyboard

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db

# In-memory state machine for add MCP flow
# { user_id: { "step": "name"|"url"|"desc", "name": str, "url": str, "msg_id": int, "chat_id": int } }
_add_mcp_state: dict = {}


# ==================== Pagination ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/page/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_page_handler(client: Client, callback_query: types.CallbackQuery):
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    page = int(parts[3])
    await show_mcp_servers_list(client, callback_query.message, page)
    await callback_query.answer()


# ==================== Back / Close ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/back$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Back to admin panel"""
    from app.handlers.admin.admin_callbacks import ADMIN_PANEL_TEXT, _build_admin_panel_keyboard
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    try:
        await callback_query.message.edit_text(
            ADMIN_PANEL_TEXT,
            reply_markup=_build_admin_panel_keyboard(),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/close$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_close_handler(client: Client, callback_query: types.CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


# ==================== Select server by number ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/(\d+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_number_handler(client: Client, callback_query: types.CallbackQuery):
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    mcp_num = int(parts[2])
    servers = await read_db.get_all_mcp_servers()
    if 1 <= mcp_num <= len(servers):
        await show_mcp_actions(client, callback_query.message, servers[mcp_num - 1])
    else:
        await callback_query.answer("Invalid MCP server number!", show_alert=True)
    await callback_query.answer()


# ==================== Toggle ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/toggle/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_toggle_handler(client: Client, callback_query: types.CallbackQuery):
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    server_name = callback_query.data.split("/", 3)[3]
    result = await write_db.toggle_mcp_server(server_name)
    if result is None:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    status = "✅ Enabled" if result else "❌ Disabled"
    await callback_query.answer(f"{server_name} is now {status}.")
    server = await read_db.get_mcp_server_by_name(server_name)
    if server:
        await show_mcp_actions(client, callback_query.message, server)


# ==================== Delete (with confirmation) ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/delete/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_delete_handler(client: Client, callback_query: types.CallbackQuery):
    """Show delete confirmation dialog"""
    server_name = callback_query.data.split("/", 3)[3]
    markup = types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="✅ Yes, Delete",
                callback_data=f"admin:mcp/delete_confirm/{server_name}"
            ),
            types.InlineKeyboardButton(
                text="⬅️ Cancel",
                callback_data=f"admin:mcp/actions/{server_name}"
            ),
        ],
    ])
    try:
        await callback_query.message.edit_text(
            f"**🗑️ Delete MCP Server?**\n\n"
            f"Are you sure you want to delete `{server_name}`?\n"
            f"This action cannot be undone.",
            reply_markup=markup,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/delete_confirm/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_delete_confirm_handler(client: Client, callback_query: types.CallbackQuery):
    """Execute deletion after confirmation"""
    server_name = callback_query.data.split("/", 3)[3]
    result = await write_db.delete_mcp_server(server_name)
    if result:
        await callback_query.answer(f"🗑️ {server_name} deleted!")
        await show_mcp_servers_list(client, callback_query.message, 0)
    else:
        await callback_query.answer("MCP server not found!", show_alert=True)


# ==================== Tools view ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/tools/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_tools_handler(client: Client, callback_query: types.CallbackQuery):
    server_name = callback_query.data.split("/", 3)[3]
    server = await read_db.get_mcp_server_by_name(server_name)
    if not server:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    tools_config = server.tools_config or {}
    if tools_config:
        tools_text = "\n".join(
            f"{('✅' if en else '❌')} `{name}`"
            for name, en in tools_config.items()
        )
    else:
        tools_text = "No tools configured yet."
    markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="⬅️ Back", callback_data=f"admin:mcp/actions/{server.name}"
        )
    ]])
    try:
        await callback_query.message.edit_text(
            f"**🛠️ Tools for {server.name}**\n\n{tools_text}\n\nTools management coming soon.",
            reply_markup=markup,
        )
    except Exception:
        pass
    await callback_query.answer()


# ==================== Back to actions ====================

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/actions/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_actions_back_handler(client: Client, callback_query: types.CallbackQuery):
    server_name = callback_query.data.split("/", 3)[3]
    server = await read_db.get_mcp_server_by_name(server_name)
    if not server:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    await show_mcp_actions(client, callback_query.message, server)
    await callback_query.answer()


# ==================== Add MCP - Button Flow ====================


def _cancel_markup(back_callback: str | None = None) -> types.InlineKeyboardMarkup:
    rows = []
    if back_callback:
        rows.append([types.InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback)])
    rows.append([types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")])
    return types.InlineKeyboardMarkup(rows)


def _auth_markup() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="🌐 No Auth", callback_data="admin:mcp/add_auth/none")],
        [types.InlineKeyboardButton(text="🔑 Bearer Token", callback_data="admin:mcp/add_auth/bearer")],
        [types.InlineKeyboardButton(text="🔐 OAuth 2.0", callback_data="admin:mcp/add_auth/oauth")],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/url")],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")],
    ])


def _description_markup() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="⏭️ Skip Description", callback_data="admin:mcp/add_skip_desc")],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")],
    ])


def _oauth_callback_path(oauth_state: str) -> Path:
    return Path(tempfile.gettempdir()) / "starchatter-oauth" / f"{oauth_state}.json"


async def _show_auth_choice(client: Client, state: dict):
    state["step"] = "auth_select"
    await client.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["menu_msg_id"],
        text=(
            "**➕ Add MCP Server — Authentication**\n\n"
            f"**Name:** `{state['name']}`\n"
            f"**URL:** `{state['url']}`\n\n"
            "Choose the authentication required by this MCP server:"
        ),
        reply_markup=_auth_markup(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


async def _show_description_step(client: Client, state: dict):
    state["step"] = "desc"
    auth_label = {
        "none": "No Auth",
        "bearer": "Bearer Token",
        "oauth": "OAuth 2.0 (Authorization Code + PKCE)",
    }.get(state.get("auth_type", "none"), "No Auth")
    await client.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["menu_msg_id"],
        text=(
            "**➕ Add MCP Server — Description**\n\n"
            f"**Name:** `{state['name']}`\n"
            f"**URL:** `{state['url']}`\n"
            f"**Auth:** `{auth_label}`\n\n"
            "Send a **description** (optional) or press Skip:"
        ),
        reply_markup=_description_markup(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


async def _show_oauth_authorize_step(client: Client, state: dict, *, reset: bool = False):
    config = state["auth_config"]
    if reset or not state.get("oauth_state") or not state.get("oauth_code_verifier"):
        old_state = state.get("oauth_state")
        if old_state:
            try:
                _oauth_callback_path(old_state).unlink(missing_ok=True)
            except Exception:
                pass
        verifier, challenge = create_pkce_pair()
        state["oauth_state"] = secrets.token_urlsafe(32)
        state["oauth_code_verifier"] = verifier
        state["oauth_code_challenge"] = challenge

    authorization_url = build_authorization_url(
        config["authorization_url"],
        client_id=config["client_id"],
        redirect_uri=MCP_OAUTH_REDIRECT_URI,
        state=state["oauth_state"],
        code_challenge=state["oauth_code_challenge"],
        scope=config.get("scope", ""),
    )
    state["step"] = "oauth_wait"

    markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="🔐 Authorize OAuth2", url=authorization_url)],
        [types.InlineKeyboardButton(text="✅ Check Authorization", callback_data="admin:mcp/oauth_check")],
        [types.InlineKeyboardButton(text="🔄 New OAuth Link", callback_data="admin:mcp/oauth_new_link")],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")],
    ])
    await client.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["menu_msg_id"],
        text=(
            "**🔐 OAuth2 Authorization Required**\n\n"
            f"MCP Server: `{state['name']}`\n\n"
            "Press **Authorize OAuth2** to open the provider's login/consent page. "
            "After authorization returns successfully, come back here and press "
            "**Check Authorization**.\n\n"
            f"Redirect URI: `{MCP_OAUTH_REDIRECT_URI}`"
        ),
        reply_markup=markup,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_handler(client: Client, callback_query: types.CallbackQuery):
    """Start add MCP server flow."""
    user_id = callback_query.from_user.id
    _add_mcp_state[user_id] = {
        "step": "name",
        "chat_id": callback_query.message.chat.id,
        "menu_msg_id": callback_query.message.id,
        "auth_type": "none",
        "auth_config": {},
    }
    flow_state.start_flow(user_id, "mcp_add")
    await callback_query.message.edit_text(
        "**➕ Add MCP Server — Name**\n\n"
        "Please send the **server name** (e.g. `MyTools`):\n\n"
        "_Reply to this message or just type in chat._",
        reply_markup=_cancel_markup(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_cancel$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _add_mcp_state.pop(user_id, None)
    if state and state.get("oauth_state"):
        try:
            _oauth_callback_path(state["oauth_state"]).unlink(missing_ok=True)
        except Exception:
            pass
    flow_state.end_flow(user_id)
    await show_mcp_servers_list(client, callback_query.message, 0)
    await callback_query.answer("Cancelled.")


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_back/(url|auth)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_back_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state:
        await callback_query.answer("Session expired.", show_alert=True)
        return
    target = str(callback_query.data).rsplit("/", 1)[-1]
    if target == "url":
        state["step"] = "url"
        await callback_query.message.edit_text(
            "**➕ Add MCP Server — URL**\n\n"
            f"**Name:** `{state['name']}`\n\n"
            "Send the **server URL** (e.g. `https://example.com/mcp/sse`):",
            reply_markup=_cancel_markup(),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    else:
        if state.get("oauth_state"):
            try:
                _oauth_callback_path(state["oauth_state"]).unlink(missing_ok=True)
            except Exception:
                pass
        state.pop("oauth_state", None)
        state.pop("oauth_code_verifier", None)
        state.pop("oauth_code_challenge", None)
        state["auth_type"] = "none"
        state["auth_config"] = {}
        await _show_auth_choice(client, state)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_auth/(none|bearer|oauth)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_auth_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state or state.get("step") != "auth_select":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    auth_type = str(callback_query.data).rsplit("/", 1)[-1]
    state["auth_type"] = auth_type
    state["auth_config"] = {}

    if auth_type == "none":
        await _show_description_step(client, state)
    elif auth_type == "bearer":
        state["step"] = "bearer_token"
        await callback_query.message.edit_text(
            "**➕ MCP Authentication — Bearer Token**\n\n"
            "Send the **Bearer token**. Your message will be deleted immediately after reading.",
            reply_markup=_cancel_markup("admin:mcp/add_back/auth"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    else:
        state["step"] = "oauth_authorization_url"
        await callback_query.message.edit_text(
            "**➕ MCP Authentication — OAuth 2.0**\n\n"
            "This flow uses **Authorization Code + PKCE**.\n\n"
            "Send the provider's **OAuth Authorization URL** "
            "(for example `https://provider.example/oauth/authorize`):",
            reply_markup=_cancel_markup("admin:mcp/add_back/auth"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    await callback_query.answer()


@Client.on_message(
    filters.create(lambda _, __, m: (
        m.from_user is not None
        and is_user_owner(m.from_user.id)
        and m.from_user.id in _add_mcp_state
        and not (m.text or "").startswith("/")
    ))  # type: ignore
)
async def mcp_add_conversation_handler(client: Client, message: types.Message):
    """Handle step-by-step add MCP server via text replies."""
    user_id = message.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state:
        return

    text = (message.text or "").strip()
    if not text:
        return True

    step = state["step"]
    try:
        await message.delete()
    except Exception:
        pass

    if step == "name":
        state["name"] = text
        state["step"] = "url"
        await client.edit_message_text(
            chat_id=state["chat_id"],
            message_id=state["menu_msg_id"],
            text=(
                "**➕ Add MCP Server — URL**\n\n"
                f"**Name:** `{text}`\n\n"
                "Send the **server URL** (e.g. `https://example.com/mcp/sse`):"
            ),
            reply_markup=_cancel_markup(),
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    elif step == "url":
        if not text.startswith(("http://", "https://")):
            await client.edit_message_text(
                chat_id=state["chat_id"],
                message_id=state["menu_msg_id"],
                text=(
                    "**➕ Add MCP Server — URL**\n\n"
                    f"**Name:** `{state['name']}`\n\n"
                    "❌ Invalid URL. It must start with `http://` or `https://`.\n\n"
                    "Please send a valid URL:"
                ),
                reply_markup=_cancel_markup(),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            return True
        state["url"] = text
        await _show_auth_choice(client, state)

    elif step == "bearer_token":
        state["auth_config"] = {"token": text}
        await _show_description_step(client, state)

    elif step in {"oauth_authorization_url", "oauth_token_url"}:
        if not text.startswith(("http://", "https://")):
            label = "authorization" if step == "oauth_authorization_url" else "token endpoint"
            await client.edit_message_text(
                chat_id=state["chat_id"],
                message_id=state["menu_msg_id"],
                text=f"❌ Invalid OAuth {label} URL. Please send an `http://` or `https://` URL:",
                reply_markup=_cancel_markup("admin:mcp/add_back/auth"),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            return True

        if step == "oauth_authorization_url":
            state["auth_config"]["authorization_url"] = text
            state["step"] = "oauth_token_url"
            prompt = "**➕ MCP OAuth — Token URL**\n\nSend the OAuth **token endpoint URL**:"
        else:
            state["auth_config"]["token_url"] = text
            state["step"] = "oauth_client_id"
            prompt = "**➕ MCP OAuth — Client ID**\n\nSend the OAuth **client_id**:"
        await client.edit_message_text(
            chat_id=state["chat_id"], message_id=state["menu_msg_id"],
            text=prompt,
            reply_markup=_cancel_markup("admin:mcp/add_back/auth"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    elif step == "oauth_client_id":
        state["auth_config"]["client_id"] = text
        state["step"] = "oauth_client_secret"
        secret_markup = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(text="⏭️ No Client Secret", callback_data="admin:mcp/add_skip_client_secret")],
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
            [types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")],
        ])
        await client.edit_message_text(
            chat_id=state["chat_id"], message_id=state["menu_msg_id"],
            text=(
                "**➕ MCP OAuth — Client Secret**\n\n"
                "Send the OAuth **client_secret**, or press No Client Secret for a public/PKCE client. "
                "Your secret message will be deleted immediately after reading."
            ),
            reply_markup=secret_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    elif step == "oauth_client_secret":
        state["auth_config"]["client_secret"] = text
        await _show_oauth_scope_step(client, state)

    elif step == "oauth_scope":
        state["auth_config"]["scope"] = text
        await _show_description_step(client, state)

    elif step == "desc":
        state["desc"] = text
        await _finalize_add_mcp(client, user_id, state, state["chat_id"])

    return True


async def _show_oauth_scope_step(client: Client, state: dict):
    state["step"] = "oauth_scope"
    scope_markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="⏭️ No Scope", callback_data="admin:mcp/add_skip_scope")],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="admin:mcp/add_cancel")],
    ])
    await client.edit_message_text(
        chat_id=state["chat_id"], message_id=state["menu_msg_id"],
        text="**➕ MCP OAuth — Scope**\n\nSend OAuth **scope** (space-separated), or press No Scope:",
        reply_markup=scope_markup,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_skip_client_secret$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_skip_client_secret_handler(client: Client, callback_query: types.CallbackQuery):
    state = _add_mcp_state.get(callback_query.from_user.id)
    if not state or state.get("step") != "oauth_client_secret":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    state["auth_config"]["client_secret"] = ""
    await _show_oauth_scope_step(client, state)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_skip_scope$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_skip_scope_handler(client: Client, callback_query: types.CallbackQuery):
    state = _add_mcp_state.get(callback_query.from_user.id)
    if not state or state.get("step") != "oauth_scope":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    state["auth_config"]["scope"] = ""
    await _show_description_step(client, state)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_skip_desc$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_skip_desc_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state or state.get("step") != "desc":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    state["desc"] = None
    await _finalize_add_mcp(
        client, user_id, state, state["chat_id"], message=callback_query.message
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/oauth_new_link$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_oauth_new_link_handler(client: Client, callback_query: types.CallbackQuery):
    state = _add_mcp_state.get(callback_query.from_user.id)
    if not state or state.get("step") != "oauth_wait":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    await _show_oauth_authorize_step(client, state, reset=True)
    await callback_query.answer("New OAuth link generated.")


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/oauth_check$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_oauth_check_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state or state.get("step") != "oauth_wait":
        await callback_query.answer("Session expired.", show_alert=True)
        return

    oauth_state = state.get("oauth_state", "")
    callback_file = _oauth_callback_path(oauth_state)
    if not callback_file.exists():
        await callback_query.answer("OAuth callback has not arrived yet.", show_alert=True)
        return

    try:
        payload = json.loads(callback_file.read_text())
    except Exception as exc:
        await callback_query.answer(f"Invalid OAuth callback: {exc}", show_alert=True)
        return
    finally:
        try:
            callback_file.unlink(missing_ok=True)
        except Exception:
            pass

    if payload.get("state") != oauth_state:
        await callback_query.answer("OAuth state mismatch. Generate a new link.", show_alert=True)
        return

    if payload.get("error"):
        detail = payload.get("error_description") or payload.get("error")
        await callback_query.message.edit_text(
            f"**❌ OAuth Authorization Failed**\n\n`{detail}`",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton(text="🔄 Try Again", callback_data="admin:mcp/oauth_new_link")],
                [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
            ]),
        )
        await callback_query.answer()
        return

    code = str(payload.get("code") or "")
    if not code:
        await callback_query.answer("OAuth callback did not contain an authorization code.", show_alert=True)
        return

    try:
        state["auth_config"] = await exchange_authorization_code(
            state["auth_config"],
            code=code,
            code_verifier=state["oauth_code_verifier"],
            redirect_uri=MCP_OAUTH_REDIRECT_URI,
        )
    except Exception as exc:
        await callback_query.message.edit_text(
            f"**❌ OAuth Token Exchange Failed**\n\n`{exc}`",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton(text="🔄 New OAuth Link", callback_data="admin:mcp/oauth_new_link")],
                [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/add_back/auth")],
            ]),
        )
        await callback_query.answer()
        return

    await _save_mcp_server(client, user_id, state, state["chat_id"], message=callback_query.message)
    await callback_query.answer("OAuth authorized successfully.")


async def _finalize_add_mcp(
    client: Client,
    user_id: int,
    state: dict,
    chat_id: int,
    message: types.Message | None = None,
):
    """Authorize OAuth when needed, otherwise save the MCP server."""
    if state.get("auth_type") == "oauth" and not state.get("auth_config", {}).get("access_token"):
        await _show_oauth_authorize_step(client, state)
        return
    await _save_mcp_server(client, user_id, state, chat_id, message=message)


async def _save_mcp_server(
    client: Client,
    user_id: int,
    state: dict,
    chat_id: int,
    message: types.Message | None = None,
):
    """Save MCP server to DB and show result without exposing credentials."""
    name = state["name"]
    url = state["url"]
    desc = state.get("desc")
    auth_type = state.get("auth_type", "none")
    auth_config = state.get("auth_config") or {}
    menu_msg_id = state["menu_msg_id"]
    _add_mcp_state.pop(user_id, None)
    flow_state.end_flow(user_id)

    auth_label = {
        "none": "No Auth",
        "bearer": "Bearer Token",
        "oauth": "OAuth 2.0 (Authorization Code + PKCE)",
    }.get(auth_type, auth_type)

    try:
        await write_db.add_mcp_server(
            name, url, desc, enabled=True,
            auth_type=auth_type, auth_config=auth_config,
        )
        result_text = (
            "**✅ MCP Server Added!**\n\n"
            f"**Name:** `{name}`\n"
            f"**URL:** `{url}`\n"
            f"**Auth:** `{auth_label}`\n"
            f"**Description:** {desc or 'None'}\n"
            "**Status:** ✅ Enabled"
        )
    except Exception as e:
        result_text = f"**❌ Failed to add MCP server**\n\n`{e}`"

    servers = await read_db.get_all_mcp_servers()
    servers_list = [(s.id, s.name) for s in servers]
    total_pages = max(1, (len(servers_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    markup = create_providers_keyboard(
        providers=servers_list[:ITEMS_PER_PAGE],
        page=0,
        callback_prefix="admin:mcp",
        total_pages=total_pages,
        back_callback="admin:mcp/back",
    )
    markup.inline_keyboard.insert(0, [
        types.InlineKeyboardButton(text="➕ Add Server", callback_data="admin:mcp/add")
    ])

    server_names_list = []
    for i, (sid, sname) in enumerate(servers_list[:ITEMS_PER_PAGE]):
        server_obj = next((s for s in servers if s.id == sid), None)
        status_icon = "✅" if server_obj and server_obj.enabled else "❌"
        server_names_list.append(f"`{i + 1}`. {status_icon} `{sname}`")

    servers_text = "\n".join(server_names_list)
    list_text = (
        f"{result_text}\n\n---\n"
        f"**🔧 MCP Servers** (Page 1/{total_pages})\n\n"
        f"{servers_text}\n\n"
        "Tap a number to manage server."
    )

    try:
        if message:
            await message.edit_text(list_text, reply_markup=markup)
        else:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=menu_msg_id,
                text=list_text,
                reply_markup=markup,
            )
    except Exception:
        pass


# ==================== Helper Functions ====================

async def show_mcp_servers_list(client: Client, message: types.Message, page: int = 0):
    """Display MCP servers list with pagination using edit_text."""
    servers = await read_db.get_all_mcp_servers()

    add_button_row = [
        types.InlineKeyboardButton(
            text="➕ Add Server", callback_data="admin:mcp/add"
        )
    ]

    if not servers:
        markup = types.InlineKeyboardMarkup([
            [add_button_row[0]],
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:mcp/back")],
        ])
        try:
            await message.edit_text(
                "**🔧 MCP Servers**\n\nNo MCP servers yet.\n\n"
                "Tap **➕ Add Server** to add one.",
                reply_markup=markup,
            )
        except Exception:
            pass
        return

    servers_list = [(s.id, s.name) for s in servers]
    total_pages = max(1, (len(servers_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(servers_list))
    page_servers = servers_list[start_idx:end_idx]

    markup = create_providers_keyboard(
        providers=page_servers,
        page=page,
        callback_prefix="admin:mcp",
        total_pages=total_pages,
        back_callback="admin:mcp/back",
    )
    # Insert "➕ Add Server" button at the top
    markup.inline_keyboard.insert(0, [add_button_row[0]])

    start_num = page * ITEMS_PER_PAGE + 1
    server_names = []
    for i, (sid, sname) in enumerate(page_servers):
        num = start_num + i
        server_obj = next((s for s in servers if s.id == sid), None)
        status = "✅" if server_obj and server_obj.enabled else "❌"
        server_names.append(f"`{num}`. {status} `{sname}`")

    servers_text = "\n".join(server_names)
    new_text = (
        f"**🔧 MCP Servers** (Page {page + 1}/{total_pages})\n\n"
        f"{servers_text}\n\n"
        f"Tap a number to manage, or ➕ to add new server."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass


async def show_mcp_actions(client: Client, message: types.Message, server: MCPServer):
    """Display action buttons for a specific MCP server using edit_text."""
    toggle_text = "❌ Disable" if server.enabled else "✅ Enable"
    status = "✅ Enabled" if server.enabled else "❌ Disabled"

    buttons = [
        [types.InlineKeyboardButton(text=f"🔹 {server.name}", callback_data="noop")],
        [
            types.InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"admin:mcp/toggle/{server.name}"
            ),
            types.InlineKeyboardButton(
                text="🗑️ Delete",
                callback_data=f"admin:mcp/delete/{server.name}"
            ),
        ],
        [types.InlineKeyboardButton(
            text="🛠️ Tools",
            callback_data=f"admin:mcp/tools/{server.name}"
        )],
        [types.InlineKeyboardButton(
            text="⬅️ Back to MCP List",
            callback_data="admin:mcp/back"
        )],
    ]
    markup = types.InlineKeyboardMarkup(buttons)

    auth_label = {
        "none": "No Auth",
        "bearer": "Bearer Token",
        "oauth": "OAuth 2.0 (Authorization Code + PKCE)",
    }.get(getattr(server, "auth_type", None) or "none", "Unknown")

    new_text = (
        f"**🔧 MCP Server: {server.name}**\n\n"
        f"**URL:** `{server.url}`\n"
        f"**Auth:** `{auth_label}`\n"
        f"**Description:** {server.description or 'None'}\n"
        f"**Status:** {status}\n\n"
        f"Use buttons below to manage this server."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass
