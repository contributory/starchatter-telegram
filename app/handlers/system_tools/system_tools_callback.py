"""System Tools callbacks for managing Telegram native tools."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner
from typing import Dict, List


# System Tool Registry - Fixed set of Telegram capabilities
SYSTEM_TOOLS_REGISTRY: Dict[str, dict] = {
    "telegram.delete_message": {
        "tool_id": "telegram.delete_message",
        "name": "Delete Message",
        "description": "Allows AI to delete Telegram messages.",
        "enabled": True,
        "destructive": True,
        "parameters": ["chat_id", "message_id"],
    },
    "telegram.edit_message": {
        "tool_id": "telegram.edit_message",
        "name": "Edit Message",
        "description": "Allows AI to edit Telegram messages.",
        "enabled": True,
        "destructive": False,
        "parameters": ["chat_id", "message_id", "text", "parse_mode"],
    },
    "telegram.reply_message": {
        "tool_id": "telegram.reply_message",
        "name": "Reply to Message",
        "description": "Send a reply to a specific message.",
        "enabled": True,
        "destructive": False,
        "parameters": ["chat_id", "message_id", "text"],
    },
    "telegram.send_sticker": {
        "tool_id": "telegram.send_sticker",
        "name": "Send Sticker",
        "description": "Send a sticker to chat.",
        "enabled": False,
        "destructive": False,
        "parameters": ["chat_id", "sticker"],
    },
    "telegram.restrict_user": {
        "tool_id": "telegram.restrict_user",
        "name": "Restrict / Mute User",
        "description": "Temporarily restrict user permissions.",
        "enabled": True,
        "destructive": True,
        "parameters": ["chat_id", "user_id", "until_date", "permissions"],
        "configuration": {"max_duration": 3600},
    },
    "telegram.kick_user": {
        "tool_id": "telegram.kick_user",
        "name": "Kick User",
        "description": "Remove user from group (destructive action).",
        "enabled": False,
        "destructive": True,
        "parameters": ["chat_id", "user_id"],
        "configuration": {"allow_ai_kick": False},
    },
    "telegram.unban_user": {
        "tool_id": "telegram.unban_user",
        "name": "Unban User",
        "description": "Unban a user from chat.",
        "enabled": True,
        "destructive": False,
        "parameters": ["chat_id", "user_id"],
    },
    "telegram.edit_group_description": {
        "tool_id": "telegram.edit_group_description",
        "name": "Edit Group Description",
        "description": "Edit the description of a group.",
        "enabled": True,
        "destructive": False,
        "parameters": ["chat_id", "description"],
    },
    "telegram.edit_channel_description": {
        "tool_id": "telegram.edit_channel_description",
        "name": "Edit Channel Description",
        "description": "Edit the description of a channel.",
        "enabled": True,
        "destructive": False,
        "parameters": ["chat_id", "description"],
    },
    "telegram.post_to_channel": {
        "tool_id": "telegram.post_to_channel",
        "name": "Post to Channel",
        "description": "Post content to a channel.",
        "enabled": False,
        "destructive": False,
        "parameters": ["chat_id", "text", "parse_mode"],
        "configuration": {"allow_ai_post_to_channel": False},
    },
}


async def get_system_tool(tool_id: str) -> dict | None:
    """Get system tool by ID."""
    return SYSTEM_TOOLS_REGISTRY.get(tool_id)


async def toggle_system_tool(tool_id: str) -> bool | None:
    """Toggle system tool enabled state."""
    if tool_id not in SYSTEM_TOOLS_REGISTRY:
        return None
    
    current_state = SYSTEM_TOOLS_REGISTRY[tool_id]["enabled"]
    SYSTEM_TOOLS_REGISTRY[tool_id]["enabled"] = not current_state
    return SYSTEM_TOOLS_REGISTRY[tool_id]["enabled"]


async def show_system_tools(client: Client, message: types.Message) -> types.InlineKeyboardMarkup:
    """Display system tools list with status."""
    
    # Categorize tools
    message_tools = [
        "telegram.delete_message",
        "telegram.edit_message",
        "telegram.reply_message",
        "telegram.send_sticker",
    ]
    moderation_tools = [
        "telegram.restrict_user",
        "telegram.kick_user",
        "telegram.unban_user",
    ]
    management_tools = [
        "telegram.edit_group_description",
        "telegram.edit_channel_description",
        "telegram.post_to_channel",
    ]
    
    def create_tool_button(tool_id: str) -> types.InlineKeyboardButton:
        tool = SYSTEM_TOOLS_REGISTRY.get(tool_id, {})
        name = tool.get("name", tool_id)
        enabled = tool.get("enabled", False)
        status = "✓" if enabled else "✗"
        return types.InlineKeyboardButton(
            text=f"{status} {name}",
            callback_data=f"admin:system_tool:view:{tool_id}"
        )
    
    keyboard = []
    
    # Message Tools section
    keyboard.append([types.InlineKeyboardButton(text="📩 MESSAGE TOOLS", callback_data="noop")])
    for tool_id in message_tools:
        keyboard.append([create_tool_button(tool_id)])
    
    # Moderation Tools section
    keyboard.append([types.InlineKeyboardButton(text="🛡️ USER MODERATION TOOLS", callback_data="noop")])
    for tool_id in moderation_tools:
        keyboard.append([create_tool_button(tool_id)])
    
    # Management Tools section
    keyboard.append([types.InlineKeyboardButton(text="📢 GROUP / CHANNEL MANAGEMENT", callback_data="noop")])
    for tool_id in management_tools:
        keyboard.append([create_tool_button(tool_id)])
    
    # Back button
    keyboard.append([
        types.InlineKeyboardButton(text="⬅️ Back", callback_data="admin:back")
    ])
    
    return types.InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(
    filters.regex(r"^admin:system_tool:view:([^:]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def system_tool_view_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle system tool view callback."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    parts = callback_query.data.split(":")
    tool_id = parts[3] if len(parts) > 3 else ""
    
    tool = await get_system_tool(tool_id)
    if not tool:
        await callback_query.answer("Tool not found!", show_alert=True)
        return
    
    status_text = "Enabled" if tool["enabled"] else "Disabled"
    status_emoji = "✅" if tool["enabled"] else "❌"
    toggle_text = "Disable" if tool["enabled"] else "Enable"
    
    buttons = [
        [
            types.InlineKeyboardButton(
                text=f"{status_emoji} {toggle_text}",
                callback_data=f"admin:system_tool:toggle:{tool_id}"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⬅️ Back",
                callback_data="admin:system_tools"
            ),
        ],
    ]
    markup = types.InlineKeyboardMarkup(buttons)
    
    await callback_query.message.edit_text(
        f"**Telegram System Tool**\n\n"
        f"**Name:** {tool['name']}\n\n"
        f"**Description:** {tool['description']}\n\n"
        f"**Status:** {status_text}\n\n"
        f"**Destructive:** {'Yes' if tool['destructive'] else 'No'}\n",
        reply_markup=markup,
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^admin:system_tool:toggle:([^:]+)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def system_tool_toggle_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle system tool toggle callback."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    parts = callback_query.data.split(":")
    tool_id = parts[3] if len(parts) > 3 else ""
    
    new_state = await toggle_system_tool(tool_id)
    if new_state is None:
        await callback_query.answer("Tool not found!", show_alert=True)
        return
    
    status = "✅ Enabled" if new_state else "❌ Disabled"
    await callback_query.answer(f"Tool {status}")
    
    # Refresh the tool view
    tool = await get_system_tool(tool_id)
    if tool:
        status_text = "Enabled" if tool["enabled"] else "Disabled"
        status_emoji = "✅" if tool["enabled"] else "❌"
        toggle_text = "Disable" if tool["enabled"] else "Enable"
        
        buttons = [
            [
                types.InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"admin:system_tool:toggle:{tool_id}"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data="admin:system_tools"
                ),
            ],
        ]
        markup = types.InlineKeyboardMarkup(buttons)
        
        await callback_query.message.edit_text(
            f"**Telegram System Tool**\n\n"
            f"**Name:** {tool['name']}\n\n"
            f"**Description:** {tool['description']}\n\n"
            f"**Status:** {status_text}\n\n"
            f"**Destructive:** {'Yes' if tool['destructive'] else 'No'}\n",
            reply_markup=markup,
        )
