"""Admin callbacks for navigating admin panel."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner


def _build_admin_panel_keyboard() -> types.InlineKeyboardMarkup:
    """Build the admin panel inline keyboard."""
    from app.config import WEB_PANEL_URL

    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🤖 Providers", callback_data="admin:providers"
            ),
            types.InlineKeyboardButton(
                text="📋 Models", callback_data="admin:models"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="🔧 MCP Servers", callback_data="admin:mcp_servers"
            ),
            types.InlineKeyboardButton(
                text="🛠️ System Tools", callback_data="admin:system_tools"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="💬 Chat Settings", callback_data="admin:chat_settings"
            ),
            types.InlineKeyboardButton(
                text="🤖 Bot Settings", callback_data="admin:bot_settings"
            ),
        ],
    ]
    if WEB_PANEL_URL:
        keyboard.append([
            types.InlineKeyboardButton(
                text="🌐 Web Panel", url=WEB_PANEL_URL
            ),
        ])
    return types.InlineKeyboardMarkup(keyboard)


ADMIN_PANEL_TEXT = "**🔧 Starchatter Admin Panel**\n\nSelect a section to manage:"


async def _edit_admin_panel(callback_query: types.CallbackQuery):
    """Edit message to show admin panel."""
    try:
        await callback_query.message.edit_text(
            ADMIN_PANEL_TEXT,
            reply_markup=_build_admin_panel_keyboard(),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass  # Message may be unchanged


@Client.on_callback_query(
    filters.regex(r"^admin:(providers|models|mcp_servers|system_tools|chat_settings|bot_settings|back)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def admin_navigation_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle admin panel navigation callbacks."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    data = callback_query.data
    action = data.split(":")[1] if ":" in data else ""
    
    if action == "back":
        # Return to main admin panel
        await _edit_admin_panel(callback_query)
        await callback_query.answer()
        return
    
    elif action == "providers":
        # Edit message to show providers list
        from app.handlers.provider_callbacks import show_providers_list
        await show_providers_list(
            client, callback_query.message, 0, force_cloud=False,
            viewer_user_id=callback_query.from_user.id, back_callback="admin:back",
        )
        await callback_query.answer()
        return
    
    elif action == "models":
        # Edit message to show models list
        from app.handlers.models_callbacks import edit_models_list
        await edit_models_list(client, callback_query.message, 0)
        await callback_query.answer()
        return
    
    elif action == "mcp_servers":
        # Edit message to show MCP servers list
        from app.handlers.mcp_callbacks import show_mcp_servers_list
        await show_mcp_servers_list(client, callback_query.message, 0)
        await callback_query.answer()
        return
    
    elif action == "system_tools":
        from app.handlers.system_tools.system_tools_callback import show_system_tools
        await callback_query.message.edit_text(
            "**🛠️ Telegram System Tools**\n\nManage native Telegram capabilities for AI.",
            reply_markup=await show_system_tools(client, callback_query.message),
        )
        await callback_query.answer()
        return
    
    elif action == "chat_settings":
        await callback_query.answer("💬 Chat settings coming soon!", show_alert=True)
        return
    
    elif action == "bot_settings":
        await callback_query.answer("🤖 Bot settings coming soon!", show_alert=True)
        return
