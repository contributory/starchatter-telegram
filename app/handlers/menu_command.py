"""Menu command handler with inline keyboard buttons - Updated for admin panel."""

from app.handlers.owner import is_user_owner
from pyrogram import Client, enums, filters, types

from app.database.local import local_db


@Client.on_message(filters.command("menu"))  # type: ignore
async def menu_handler(client: Client, message: types.Message):
    """Show main menu with action buttons"""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    # Create inline keyboard with menu buttons
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🤖 Providers",
                callback_data="admin:providers"
            ),
            types.InlineKeyboardButton(
                text="🔧 MCP Servers",
                callback_data="admin:mcp_servers"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⚙️ Models",
                callback_data="admin:models"
            ),
            types.InlineKeyboardButton(
                text="🛠️ Tools",
                callback_data="admin:system_tools"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="❌ Close",
                callback_data="menu:close"
            ),
        ],
    ]
    
    markup = types.InlineKeyboardMarkup(keyboard)
    
    menu_text = """**📱 Main Menu**

Choose an option:

🤖 **Providers** - Manage AI providers
🔧 **MCP Servers** - Manage MCP servers  
⚙️ **Models** - Configure models
🛠️ **Tools** - Manage tools

Use /help for available commands.
"""
    
    await message.reply(
        menu_text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.create(lambda _, __, cbq: cbq.data.startswith("menu/"))  # type: ignore
)
async def menu_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle menu button callbacks"""
    from app.handlers.providers_command import providers_handler
    from app.handlers.models_command import models_handler
    
    data = callback_query.data
    action = data.split("/")[1] if "/" in data else ""
    
    # Check if user is owner
    if not is_user_owner(callback_query.from_user.id):
        await callback_query.answer("❌ Only owners can use this menu.", show_alert=True)
        return
    
    if action == "close":
        await callback_query.message.delete()
        return
    
    elif action == "providers":
        await callback_query.answer("Opening providers menu...")
        await callback_query.message.delete()
        # Forward to providers handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/providers",
        )
        await providers_handler(client, fake_message, page=0)
        
    elif action == "mcp_servers":
        await callback_query.answer("Opening MCP servers menu...")
        await callback_query.message.delete()
        # Forward to mcp_servers handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
        )
        from app.handlers.mcp_callbacks import show_mcp_servers_list
        await show_mcp_servers_list(client, fake_message, 0)
        
    elif action == "models":
        await callback_query.answer("Opening models menu...")
        await callback_query.message.delete()
        # Forward to models handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/models",
        )
        await models_handler(client, fake_message, page=0)
        
    elif action == "tools":
        await callback_query.answer("Opening system tools menu...")
        from app.handlers.system_tools.system_tools_callback import show_system_tools
        await callback_query.message.edit_text(
            "**Telegram System Tools**\n\nManage native Telegram capabilities for AI.",
            reply_markup=await show_system_tools(client, callback_query.message),
        )
        return
