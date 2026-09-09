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
