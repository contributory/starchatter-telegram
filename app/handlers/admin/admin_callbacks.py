"""Admin callbacks for navigating admin panel."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner


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
        from app.handlers.admin.super_command import super_command
        # Delete current message and show admin panel again
        await callback_query.message.delete()
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/super",
        )
        await super_command(client, fake_message)
        await callback_query.answer()
        return
    
    elif action == "providers":
        await callback_query.answer("Opening providers menu...")
        from app.handlers.providers_command import providers_handler
        await callback_query.message.delete()
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/providers",
        )
        await providers_handler(client, fake_message, page=0)
        await callback_query.answer()
        return
    
    elif action == "models":
        await callback_query.answer("Opening models menu...")
        from app.handlers.models_command import models_handler
        await callback_query.message.delete()
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/models",
        )
        await models_handler(client, fake_message, page=0)
        await callback_query.answer()
        return
    
    elif action == "mcp_servers":
        await callback_query.answer("Opening MCP servers menu...")
        await callback_query.message.delete()
        from app.handlers.mcp_callbacks import show_mcp_servers_list
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
        )
        await show_mcp_servers_list(client, fake_message, 0)
        await callback_query.answer()
        return
    
    elif action == "system_tools":
        await callback_query.answer("Opening system tools menu...")
        from .system_tools_callback import show_system_tools
        await callback_query.message.edit_text(
            "**Telegram System Tools**\n\nManage native Telegram capabilities for AI.",
            reply_markup=await show_system_tools(client, callback_query.message),
        )
        await callback_query.answer()
        return
    
    elif action == "chat_settings":
        await callback_query.answer("Chat settings coming soon!")
        return
    
    elif action == "bot_settings":
        await callback_query.answer("Bot settings coming soon!")
        return
