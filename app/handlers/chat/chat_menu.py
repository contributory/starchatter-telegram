"""Chat menu handlers for /chat command."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner
from typing import Dict

# Chat state per chat (in-memory for now, can be persisted)
chat_states: Dict[int, dict] = {}


async def get_chat_state(chat_id: int) -> dict:
    """Get chat state for a specific chat."""
    if chat_id not in chat_states:
        chat_states[chat_id] = {
            "enabled": True,
            "conversations": [],
            "current_conversation": None,
        }
    return chat_states[chat_id]


async def toggle_chat(chat_id: int) -> bool:
    """Toggle chat enabled state."""
    state = await get_chat_state(chat_id)
    state["enabled"] = not state["enabled"]
    return state["enabled"]


async def reset_chat(chat_id: int) -> bool:
    """Reset chat history."""
    state = await get_chat_state(chat_id)
    state["current_conversation"] = None
    return True


@Client.on_message(filters.command("chat"))  # type: ignore
async def chat_command(client: Client, message: types.Message):
    """Show chat menu with inline keyboard buttons."""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    chat_id = message.chat.id
    state = await get_chat_state(chat_id)
    
    # Determine enable/disable button text
    if state["enabled"]:
        toggle_text = "❌ Disable"
        toggle_callback = "chat:toggle"
    else:
        toggle_text = "✅ Enable"
        toggle_callback = "chat:toggle"
    
    # Create inline keyboard
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🔄 Reset Chat",
                callback_data="chat:reset"
            ),
            types.InlineKeyboardButton(
                text="💾 Save Conversation",
                callback_data="chat:save"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="📁 Conversations",
                callback_data="chat:conversations"
            ),
            types.InlineKeyboardButton(
                text=toggle_text,
                callback_data=toggle_callback
            ),
        ],
    ]
    
    markup = types.InlineKeyboardMarkup(keyboard)
    
    chat_text = """**Chat Menu**

Manage your conversation settings and history.
"""
    
    await message.reply(
        chat_text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.regex(r"^chat:(reset|save|conversations|toggle)$")
)
async def chat_menu_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle chat menu callbacks."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    data = callback_query.data
    action = data.split(":")[1] if ":" in data else ""
    chat_id = callback_query.message.chat.id
    
    if action == "toggle":
        new_state = await toggle_chat(chat_id)
        status = "✅ Enabled" if new_state else "❌ Disabled"
        await callback_query.answer(f"Chat {status}")
        
        # Refresh the menu
        state = await get_chat_state(chat_id)
        if state["enabled"]:
            toggle_text = "❌ Disable"
        else:
            toggle_text = "✅ Enable"
        
        keyboard = [
            [
                types.InlineKeyboardButton(
                    text="🔄 Reset Chat",
                    callback_data="chat:reset"
                ),
                types.InlineKeyboardButton(
                    text="💾 Save Conversation",
                    callback_data="chat:save"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="📁 Conversations",
                    callback_data="chat:conversations"
                ),
                types.InlineKeyboardButton(
                    text=toggle_text,
                    callback_data="chat:toggle"
                ),
            ],
        ]
        markup = types.InlineKeyboardMarkup(keyboard)
        
        await callback_query.message.edit_text(
            "**Chat Menu**\n\nManage your conversation settings and history.",
            reply_markup=markup,
        )
        await callback_query.answer()
        return
    
    elif action == "reset":
        # Show confirmation
        keyboard = [
            [
                types.InlineKeyboardButton(
                    text="✅ Yes, Reset",
                    callback_data="chat:reset:confirm"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="chat:menu"
                ),
            ],
        ]
        markup = types.InlineKeyboardMarkup(keyboard)
        
        await callback_query.message.edit_text(
            "**Are you sure you want to reset this chat?**\n\nThis will clear the current conversation history.",
            reply_markup=markup,
        )
        await callback_query.answer()
        return
    
    elif action == "save":
        # Show save format options
        keyboard = [
            [
                types.InlineKeyboardButton(
                    text="📄 Markdown",
                    callback_data="chat:save:markdown"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⬅️ Back",
                    callback_data="chat:menu"
                ),
            ],
        ]
        markup = types.InlineKeyboardMarkup(keyboard)
        
        await callback_query.message.edit_text(
            "**Save Conversation**\n\nSelect format:",
            reply_markup=markup,
        )
        await callback_query.answer()
        return
    
    elif action == "conversations":
        # Show conversations list (placeholder)
        state = await get_chat_state(chat_id)
        conversations = state.get("conversations", [])
        
        if not conversations:
            keyboard = [
                [
                    types.InlineKeyboardButton(
                        text="⬅️ Back",
                        callback_data="chat:menu"
                    ),
                ],
            ]
            markup = types.InlineKeyboardMarkup(keyboard)
            
            await callback_query.message.edit_text(
                "**Conversations**\n\nNo saved conversations yet.",
                reply_markup=markup,
            )
        else:
            # List conversations
            conv_list = "\n".join([f"- {c.get('title', 'Untitled')}" for c in conversations[-5:]])
            keyboard = [
                [
                    types.InlineKeyboardButton(
                        text="🔍 Search",
                        callback_data="chat:conversations:search"
                    ),
                ],
                [
                    types.InlineKeyboardButton(
                        text="⬅️ Back",
                        callback_data="chat:menu"
                    ),
                ],
            ]
            markup = types.InlineKeyboardMarkup(keyboard)
            
            await callback_query.message.edit_text(
                f"**Conversations**\n\n{conv_list}",
                reply_markup=markup,
            )
        
        await callback_query.answer()
        return


@Client.on_callback_query(
    filters.regex(r"^chat:reset:confirm$")
)
async def chat_reset_confirm_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle chat reset confirmation."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    chat_id = callback_query.message.chat.id
    await reset_chat(chat_id)
    
    # Show success message
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="📱 Open Menu",
                callback_data="chat:menu"
            ),
        ],
    ]
    markup = types.InlineKeyboardMarkup(keyboard)
    
    await callback_query.message.edit_text(
        "**✅ Chat has been reset.**\n\nConversation history cleared.",
        reply_markup=markup,
    )
    await callback_query.answer("Chat reset successfully!")


@Client.on_callback_query(
    filters.regex(r"^chat:menu$")
)
async def chat_menu_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Return to chat menu."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    
    chat_id = callback_query.message.chat.id
    state = await get_chat_state(chat_id)
    
    if state["enabled"]:
        toggle_text = "❌ Disable"
    else:
        toggle_text = "✅ Enable"
    
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🔄 Reset Chat",
                callback_data="chat:reset"
            ),
            types.InlineKeyboardButton(
                text="💾 Save Conversation",
                callback_data="chat:save"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="📁 Conversations",
                callback_data="chat:conversations"
            ),
            types.InlineKeyboardButton(
                text=toggle_text,
                callback_data="chat:toggle"
            ),
        ],
    ]
    markup = types.InlineKeyboardMarkup(keyboard)
    
    await callback_query.message.edit_text(
        "**Chat Menu**\n\nManage your conversation settings and history.",
        reply_markup=markup,
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^chat:save:markdown$")
)
async def chat_save_markdown_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle save conversation as markdown."""
    await callback_query.answer("Markdown export coming soon!")
