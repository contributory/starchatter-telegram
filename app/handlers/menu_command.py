"""Menu command handler with inline keyboard buttons."""

from app.handlers.owner import is_user_owner_async
from pyrogram import Client, enums, filters, types


def _build_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Build main menu inline keyboard."""
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🤖 Providers", callback_data="menu:providers"
            ),
            types.InlineKeyboardButton(
                text="🔧 MCP Servers", callback_data="menu:mcp_servers"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⚙️ Models", callback_data="menu:models"
            ),
            types.InlineKeyboardButton(
                text="🛠️ Tools", callback_data="menu:tools"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="❌ Close", callback_data="menu:close"
            ),
        ],
    ]
    return types.InlineKeyboardMarkup(keyboard)


MENU_TEXT = (
    "**📱 Main Menu**\n\n"
    "Choose an option:\n\n"
    "🤖 **Providers** - Manage AI providers\n"
    "🔧 **MCP Servers** - Manage MCP servers\n"
    "⚙️ **Models** - Configure models\n"
    "🛠️ **Tools** - Manage tools\n\n"
    "Use /help for available commands."
)


@Client.on_message(filters.command("menu"))  # type: ignore
async def menu_handler(client: Client, message: types.Message):
    """Show main menu with action buttons"""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    await message.reply(
        MENU_TEXT,
        reply_markup=_build_menu_keyboard(),
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.regex(r"^menu:(.+)$")  # type: ignore
)
async def menu_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle menu button callbacks - uses edit_text for smooth navigation"""
    data = callback_query.data
    action = data.split(":")[1] if ":" in data else ""
    
    if action == "close":
        # Delete the menu message
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer()
        return
    
    # Providers are public. Other configuration areas remain admin-only.
    if action == "providers":
        from app.handlers.provider_callbacks import show_providers_list
        await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
        await show_providers_list(
            client, callback_query.message, 0,
            force_cloud=False, viewer_user_id=callback_query.from_user.id,
        )
        await callback_query.answer()
        return

    if not await is_user_owner_async(callback_query.from_user.id):
        await callback_query.answer("❌ Only owners can use this menu.", show_alert=True)
        return

    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)

    if action == "mcp_servers":
        from app.handlers.mcp_callbacks import show_mcp_servers_list
        await show_mcp_servers_list(client, callback_query.message, 0)
        await callback_query.answer()
        
    elif action == "models":
        from app.handlers.models_callbacks import edit_models_list
        await edit_models_list(client, callback_query.message, 0)
        await callback_query.answer()
        
    elif action == "tools":
        from app.handlers.system_tools.system_tools_callback import show_system_tools
        await callback_query.message.edit_text(
            "**🛠️ Telegram System Tools**\n\nManage native Telegram capabilities for AI.",
            reply_markup=await show_system_tools(client, callback_query.message),
        )
        await callback_query.answer()
    
    else:
        await callback_query.answer("❓ Unknown action", show_alert=True)
