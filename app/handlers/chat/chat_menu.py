"""Chat menu handlers for /chat command."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner
from typing import Dict

# Chat state per chat (in-memory)
chat_states: Dict[int, dict] = {}


async def get_chat_state(chat_id: int) -> dict:
    if chat_id not in chat_states:
        chat_states[chat_id] = {"enabled": True, "conversations": [], "current_conversation": None}
    return chat_states[chat_id]


async def toggle_chat(chat_id: int) -> bool:
    state = await get_chat_state(chat_id)
    state["enabled"] = not state["enabled"]
    return state["enabled"]


async def reset_chat_history(chat_id: int):
    """Reset chat history via SQLiteSession."""
    try:
        from agents import SQLiteSession
        session = SQLiteSession(f"chat_{chat_id}", "conversations.sqlite")
        await session.clear_session()
    except Exception:
        pass


def _build_chat_menu_keyboard(enabled: bool) -> types.InlineKeyboardMarkup:
    toggle_text = "❌ Disable" if enabled else "✅ Enable"
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(text="🔄 Reset Chat", callback_data="chat:reset"),
            types.InlineKeyboardButton(text="💾 Save Conversation", callback_data="chat:save"),
        ],
        [
            types.InlineKeyboardButton(text="📁 Conversations", callback_data="chat:conversations"),
            types.InlineKeyboardButton(text=toggle_text, callback_data="chat:toggle"),
        ],
        [
            types.InlineKeyboardButton(text="❌ Close", callback_data="chat:close"),
        ],
    ])


CHAT_MENU_TEXT = "**💬 Chat Menu**\n\nManage your conversation settings and history."


@Client.on_message(filters.command("chat"))  # type: ignore
async def chat_command(client: Client, message: types.Message):
    """Show chat menu with inline keyboard buttons."""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    chat_id = message.chat.id
    state = await get_chat_state(chat_id)
    await message.reply(
        CHAT_MENU_TEXT,
        reply_markup=_build_chat_menu_keyboard(state["enabled"]),
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(filters.regex(r"^chat:(reset|save|conversations|toggle|close)$"))
async def chat_menu_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle chat menu callbacks - uses edit_text."""
    data = callback_query.data
    action = data.split(":")[1] if ":" in data else ""
    chat_id = callback_query.message.chat.id

    if action == "close":
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer()
        return

    if action == "toggle":
        new_state = await toggle_chat(chat_id)
        status = "✅ Enabled" if new_state else "❌ Disabled"
        await callback_query.answer(f"Chat {status}")
        try:
            await callback_query.message.edit_text(
                CHAT_MENU_TEXT,
                reply_markup=_build_chat_menu_keyboard(new_state),
            )
        except Exception:
            pass
        return

    elif action == "reset":
        markup = types.InlineKeyboardMarkup([
            [
                types.InlineKeyboardButton(text="✅ Yes, Reset", callback_data="chat:reset:confirm"),
                types.InlineKeyboardButton(text="⬅️ Back", callback_data="chat:menu"),
            ],
        ])
        try:
            await callback_query.message.edit_text(
                "**⚠️ Reset Chat?**\n\nThis will clear the current conversation history.",
                reply_markup=markup,
            )
        except Exception:
            pass
        await callback_query.answer()
        return

    elif action == "save":
        markup = types.InlineKeyboardMarkup([
            [
                types.InlineKeyboardButton(text="📄 Markdown", callback_data="chat:save:markdown"),
            ],
            [
                types.InlineKeyboardButton(text="⬅️ Back", callback_data="chat:menu"),
            ],
        ])
        try:
            await callback_query.message.edit_text(
                "**💾 Save Conversation**\n\nSelect format:",
                reply_markup=markup,
            )
        except Exception:
            pass
        await callback_query.answer()
        return

    elif action == "conversations":
        state = await get_chat_state(chat_id)
        conversations = state.get("conversations", [])
        if not conversations:
            text = "**📁 Conversations**\n\nNo saved conversations yet."
        else:
            conv_list = "\n".join([f"- {c.get('title', 'Untitled')}" for c in conversations[-5:]])
            text = f"**📁 Conversations**\n\n{conv_list}"

        markup = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data="chat:menu")],
        ])
        try:
            await callback_query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await callback_query.answer()
        return


@Client.on_callback_query(filters.regex(r"^chat:reset:confirm$"))
async def chat_reset_confirm_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle chat reset confirmation."""
    chat_id = callback_query.message.chat.id
    await reset_chat_history(chat_id)

    markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="chat:menu")],
    ])
    try:
        await callback_query.message.edit_text(
            "**✅ Chat Reset**\n\nConversation history cleared.",
            reply_markup=markup,
        )
    except Exception:
        pass
    await callback_query.answer("Chat reset successfully!")


@Client.on_callback_query(filters.regex(r"^chat:menu$"))
async def chat_menu_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Return to chat menu."""
    chat_id = callback_query.message.chat.id
    state = await get_chat_state(chat_id)
    try:
        await callback_query.message.edit_text(
            CHAT_MENU_TEXT,
            reply_markup=_build_chat_menu_keyboard(state["enabled"]),
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^chat:save:markdown$"))
async def chat_save_markdown_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle save conversation as markdown."""
    await callback_query.answer("Markdown export coming soon!", show_alert=True)
