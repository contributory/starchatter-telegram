"""MCP server callback handlers for managing MCP servers."""

from pyrogram import Client, enums, filters, types

from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import MCPServer
from app.handlers.owner import is_user_owner
from app.handlers.pagination import ITEMS_PER_PAGE, create_providers_keyboard

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/page/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_page_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle MCP pagination callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    page = int(parts[3])
    await show_mcp_servers_list(client, callback_query.message, page)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/back$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle back from MCP list to admin panel"""
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
    """Handle close MCP list - delete current message only"""
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/(\d+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_number_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle MCP server number selection callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    mcp_num = int(parts[2])
    
    servers = await read_db.get_all_mcp_servers()

    if 1 <= mcp_num <= len(servers):
        server = servers[mcp_num - 1]
        await show_mcp_actions(client, callback_query.message, server)
    else:
        await callback_query.answer("Invalid MCP server number!", show_alert=True)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/toggle/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_toggle_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle MCP server toggle callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    server_name = parts[3]

    result = await write_db.toggle_mcp_server(server_name)
    
    if result is None:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    
    status = "✅ Enabled" if result else "❌ Disabled"
    await callback_query.answer(f"MCP server `{server_name}` is now {status}.")
    
    # Refresh the actions view for this server
    server = await read_db.get_mcp_server_by_name(server_name)
    if server:
        await show_mcp_actions(client, callback_query.message, server)


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/delete/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_delete_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle MCP server delete callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    server_name = parts[3]

    result = await write_db.delete_mcp_server(server_name)
    
    if result:
        await callback_query.answer(f"🗑️ MCP server `{server_name}` deleted!")
        # Go back to MCP servers list
        await show_mcp_servers_list(client, callback_query.message, 0)
    else:
        await callback_query.answer("MCP server not found!", show_alert=True)


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/tools/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_tools_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle MCP server tools view callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    server_name = parts[3]

    server = await read_db.get_mcp_server_by_name(server_name)
    
    if not server:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    
    tools_config = server.tools_config or {}
    tools_text = "No tools configured yet."
    
    if tools_config:
        tools_list = []
        for tool_name, enabled in tools_config.items():
            status = "✅" if enabled else "❌"
            tools_list.append(f"{status} `{tool_name}`")
        tools_text = "\n".join(tools_list)
    
    buttons = [
        [types.InlineKeyboardButton(
            text="⬅️ Back", callback_data=f"admin:mcp/actions/{server.name}"
        )],
    ]
    markup = types.InlineKeyboardMarkup(buttons)
    
    try:
        await callback_query.message.edit_text(
            f"**🔧 Tools for {server.name}**\n\n"
            f"{tools_text}\n\n"
            f"Tools management coming soon.",
            reply_markup=markup,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/actions/([^/]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_actions_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle back to MCP server actions from tools view"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    server_name = parts[3]

    server = await read_db.get_mcp_server_by_name(server_name)
    
    if not server:
        await callback_query.answer("MCP server not found!", show_alert=True)
        return
    
    await show_mcp_actions(client, callback_query.message, server)
    await callback_query.answer()


# ==================== Helper Functions ====================

async def show_mcp_servers_list(client: Client, message: types.Message, page: int = 0):
    """Display MCP servers list with pagination using edit_text."""
    servers = await read_db.get_all_mcp_servers()
    
    if not servers:
        try:
            await message.edit_text(
                "**⚠️ No MCP Servers**\n\n"
                "Add an MCP server using:\n"
                "`/add_mcp <name> <url> [description]`",
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
    
    start_num = page * ITEMS_PER_PAGE + 1
    server_names = []
    for i, (server_id, server_name) in enumerate(page_servers):
        num = start_num + i
        server_obj = next((s for s in servers if s.id == server_id), None)
        status = "✅" if server_obj and server_obj.enabled else "❌"
        server_names.append(f"`{num}`. {status} `{server_name}`")
    
    servers_text = "\n".join(server_names)
    new_text = (
        f"**🔧 MCP Servers** (Page {page + 1}/{total_pages})\n\n"
        f"{servers_text}\n\n"
        f"Tap a number to manage server."
    )
    
    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass


async def show_mcp_actions(
    client: Client,
    message: types.Message,
    server: MCPServer,
):
    """Display action buttons for a specific MCP server using edit_text."""
    toggle_text = "❌ Disable" if server.enabled else "✅ Enable"
    buttons = [
        [types.InlineKeyboardButton(
            text=f"🔹 {server.name}", callback_data="noop"
        )],
        [
            types.InlineKeyboardButton(
                text=toggle_text, callback_data=f"admin:mcp/toggle/{server.name}"
            ),
            types.InlineKeyboardButton(
                text="🗑️ Delete", callback_data=f"admin:mcp/delete/{server.name}"
            ),
        ],
        [types.InlineKeyboardButton(
            text="🛠️ Tools", callback_data=f"admin:mcp/tools/{server.name}"
        )],
        [types.InlineKeyboardButton(
            text="⬅️ Back to MCP List", callback_data="admin:mcp/back"
        )],
    ]
    markup = types.InlineKeyboardMarkup(buttons)
    
    status = "✅ Enabled" if server.enabled else "❌ Disabled"
    new_text = (
        f"**🔧 MCP Server: {server.name}**\n\n"
        f"**URL:** `{server.url}`\n"
        f"**Description:** {server.description or 'None'}\n"
        f"**Status:** {status}\n\n"
        f"Use buttons below to manage this server."
    )
    
    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass
"""MCP server callback handlers - full button-based management."""

from pyrogram import Client, enums, filters, types

from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import MCPServer
from app.handlers.owner import is_user_owner
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

@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_handler(client: Client, callback_query: types.CallbackQuery):
    """Start add MCP server flow - ask for server name"""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    # Save state
    _add_mcp_state[user_id] = {
        "step": "name",
        "chat_id": chat_id,
        "menu_msg_id": callback_query.message.id,
    }

    cancel_markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="❌ Cancel", callback_data="admin:mcp/add_cancel"
        )
    ]])

    try:
        await callback_query.message.edit_text(
            "**➕ Add MCP Server — Step 1/3**\n\n"
            "Please send the **server name** (e.g. `MyTools`):\n\n"
            "_Reply to this message or just type in chat._",
            reply_markup=cancel_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_cancel$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    """Cancel add MCP flow"""
    user_id = callback_query.from_user.id
    _add_mcp_state.pop(user_id, None)
    await show_mcp_servers_list(client, callback_query.message, 0)
    await callback_query.answer("Cancelled.")


@Client.on_message(
    filters.create(lambda _, __, m: (
        m.from_user is not None
        and is_user_owner(m.from_user.id)
        and m.from_user.id in _add_mcp_state
        and not (m.text or "").startswith("/")
    ))  # type: ignore
)
async def mcp_add_conversation_handler(client: Client, message: types.Message):
    """Handle step-by-step add MCP server via text replies"""
    user_id = message.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state:
        return

    text = (message.text or "").strip()
    if not text:
        return

    step = state["step"]
    chat_id = state["chat_id"]

    # Delete user's reply to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass

    cancel_markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="❌ Cancel", callback_data="admin:mcp/add_cancel"
        )
    ]])

    if step == "name":
        state["name"] = text
        state["step"] = "url"
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=state["menu_msg_id"],
                text=(
                    f"**➕ Add MCP Server — Step 2/3**\n\n"
                    f"**Name:** `{text}`\n\n"
                    f"Now send the **server URL** "
                    f"(e.g. `https://example.com/mcp/sse`):"
                ),
                reply_markup=cancel_markup,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    elif step == "url":
        if not text.startswith("http://") and not text.startswith("https://"):
            try:
                await client.edit_message_text(
                    chat_id=chat_id,
                    message_id=state["menu_msg_id"],
                    text=(
                        f"**➕ Add MCP Server — Step 2/3**\n\n"
                        f"**Name:** `{state['name']}`\n\n"
                        f"❌ Invalid URL. Must start with `http://` or `https://`\n\n"
                        f"Please send a valid URL:"
                    ),
                    reply_markup=cancel_markup,
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            return

        state["url"] = text
        state["step"] = "desc"

        skip_markup = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(
                text="⏭️ Skip Description", callback_data="admin:mcp/add_skip_desc"
            )],
            [types.InlineKeyboardButton(
                text="❌ Cancel", callback_data="admin:mcp/add_cancel"
            )],
        ])
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=state["menu_msg_id"],
                text=(
                    f"**➕ Add MCP Server — Step 3/3**\n\n"
                    f"**Name:** `{state['name']}`\n"
                    f"**URL:** `{text}`\n\n"
                    f"Send a **description** (optional) or press Skip:"
                ),
                reply_markup=skip_markup,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    elif step == "desc":
        state["desc"] = text
        await _finalize_add_mcp(client, user_id, state, chat_id)


@Client.on_callback_query(
    filters.regex(r"^admin:mcp/add_skip_desc$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def mcp_add_skip_desc_handler(client: Client, callback_query: types.CallbackQuery):
    """Skip description step and finalize add"""
    user_id = callback_query.from_user.id
    state = _add_mcp_state.get(user_id)
    if not state:
        await callback_query.answer("Session expired.", show_alert=True)
        return
    state["desc"] = None
    await _finalize_add_mcp(
        client, user_id, state,
        state["chat_id"],
        message=callback_query.message
    )
    await callback_query.answer()


async def _finalize_add_mcp(
    client: Client,
    user_id: int,
    state: dict,
    chat_id: int,
    message: types.Message | None = None,
):
    """Save MCP server to DB and show result"""
    name = state["name"]
    url = state["url"]
    desc = state.get("desc")
    menu_msg_id = state["menu_msg_id"]

    _add_mcp_state.pop(user_id, None)

    try:
        await write_db.add_mcp_server(name, url, desc, enabled=True)
        result_text = (
            f"**✅ MCP Server Added!**\n\n"
            f"**Name:** `{name}`\n"
            f"**URL:** `{url}`\n"
            f"**Description:** {desc or 'None'}\n"
            f"**Status:** ✅ Enabled"
        )
    except Exception as e:
        result_text = f"**❌ Failed to add MCP server**\n\n`{e}`"

    # Reload MCP list
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
    # Add row with "➕ Add Server" button
    markup.inline_keyboard.insert(0, [
        types.InlineKeyboardButton(
            text="➕ Add Server", callback_data="admin:mcp/add"
        )
    ])

    start_num = 1
    server_names_list = []
    for i, (sid, sname) in enumerate(servers_list[:ITEMS_PER_PAGE]):
        num = start_num + i
        server_obj = next((s for s in servers if s.id == sid), None)
        status_icon = "✅" if server_obj and server_obj.enabled else "❌"
        server_names_list.append(f"`{num}`. {status_icon} `{sname}`")

    servers_text = "\n".join(server_names_list)
    list_text = (
        f"{result_text}\n\n"
        f"---\n"
        f"**🔧 MCP Servers** (Page 1/{total_pages})\n\n"
        f"{servers_text}\n\n"
        f"Tap a number to manage server."
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

    new_text = (
        f"**🔧 MCP Server: {server.name}**\n\n"
        f"**URL:** `{server.url}`\n"
        f"**Description:** {server.description or 'None'}\n"
        f"**Status:** {status}\n\n"
        f"Use buttons below to manage this server."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass
