"""Admin panel handlers for /super command."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner
from app.config import WEB_PANEL_URL


@Client.on_message(filters.command("super") & filters.create(lambda _, __, msg: is_user_owner(msg.from_user.id)))  # type: ignore
async def super_command(client: Client, message: types.Message):
    """Show administrator panel with inline keyboard buttons."""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    # Create inline keyboard with admin panel buttons
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🤖 Providers",
                callback_data="admin:providers"
            ),
            types.InlineKeyboardButton(
                text="📋 List Models",
                callback_data="admin:models"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="🔧 MCP Servers",
                callback_data="admin:mcp_servers"
            ),
            types.InlineKeyboardButton(
                text="🛠️ System Tools",
                callback_data="admin:system_tools"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="💬 Chat Settings",
                callback_data="admin:chat_settings"
            ),
            types.InlineKeyboardButton(
                text="🤖 Bot Settings",
                callback_data="admin:bot_settings"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="🌐 Web Panel",
                url=WEB_PANEL_URL or "https://example.com"
            ),
        ],
    ]
    
    markup = types.InlineKeyboardMarkup(keyboard)
    
    admin_text = """**Starchatter Administrator Panel**

Manage your bot configuration and settings.
"""
    
    await message.reply(
        admin_text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )
