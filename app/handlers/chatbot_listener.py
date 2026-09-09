import logging
import traceback

from app.ai.agent import AIAgent
from app.database.cloud import cloud_db
from app.database.local import local_db
from pyrogram import Client, enums, filters, types
from pyrogram.errors import MessageNotModified, BadRequest

logger = logging.getLogger(__name__)

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db

basic_buttons = [
    types.InlineKeyboardButton(text="Channel", url="https://t.me/starfall_org"),
    types.InlineKeyboardButton(text="Group", url="https://t.me/starfall_community"),
    types.InlineKeyboardButton(text="Discord", url="https://discord.gg/9WF54BSc4s"),
]

ERROR_MARKUP = types.InlineKeyboardMarkup([
    [
        types.InlineKeyboardButton(text="🔄 Reset Chat", callback_data="chat:reset:confirm"),
        types.InlineKeyboardButton(text="🤖 Models", callback_data="admin:models"),
    ],
])

ERROR_TEXT = (
    "⚠️ **Something went wrong.**\n\n"
    "The AI encountered a technical issue. "
    "You can reset the conversation or switch to a different model."
)


async def safe_reply(message: types.Message, text: str, reply_markup=None):
    """Safely reply, fallback to plain text if markdown fails."""
    kwargs = {"quote": True}
    if reply_markup:
        kwargs["reply_markup"] = reply_markup

    try:
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                chunk = text[i:i + 4000]
                markup = reply_markup if i + 4000 >= len(text) else None
                await message.reply(
                    chunk,
                    parse_mode=enums.ParseMode.MARKDOWN,
                    reply_markup=markup,
                    **{"quote": True},
                )
        else:
            await message.reply(
                text,
                parse_mode=enums.ParseMode.MARKDOWN,
                **kwargs,
            )
        return True
    except BadRequest as e:
        error_str = str(e).lower()
        if "can't parse" in error_str or "entities" in error_str:
            logger.warning(f"Markdown failed, retrying as plain text: {e}")
            try:
                await message.reply(text, **kwargs)
                return True
            except Exception as inner:
                logger.error(f"Plain text reply also failed: {inner}")
                return False
        logger.error(f"BadRequest: {e}")
        return False
    except MessageNotModified:
        return True
    except Exception as e:
        logger.error(f"Unexpected reply error: {e}")
        return False


@Client.on_message(
    (filters.mentioned & ~filters.new_chat_members | filters.private)
    & filters.incoming
    & ~filters.create(lambda _, __, m: m.text and m.text.startswith("/"))  # type: ignore
)
async def chatbot_handler(client: Client, message: types.Message):
    """Process chatbot message with improved error handling."""
    chat_id = message.chat.id
    chat_type = message.chat.type
    user_info = (
        f"@{message.from_user.username}" if message.from_user and message.from_user.username
        else f"user_{message.from_user.id}" if message.from_user
        else f"chat_{chat_id}"
    )

    logger.info(
        f"Received message from {user_info} in {chat_type} {chat_id}: "
        f"'{(message.text or message.caption or '')[:100]}'"
    )

    try:
        await message.reply_chat_action(enums.ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Failed to send typing action: {e}")

    try:
        agent = await AIAgent.create()
    except ValueError as e:
        logger.error(f"Failed to create AIAgent: {e}")
        await safe_reply(
            message,
            "⚠️ **Bot not configured.**\n\nNo AI provider found. Please contact admin.",
        )
        return
    except Exception as e:
        logger.error(f"Unexpected error creating AIAgent: {e}\n{traceback.format_exc()}")
        await safe_reply(message, ERROR_TEXT, reply_markup=ERROR_MARKUP)
        return

    try:
        resp = await agent.run_chat(client, message)
    except Exception as e:
        logger.error(
            f"Agent.run_chat failed for {user_info} in {chat_type} {chat_id}: "
            f"{e}\n{traceback.format_exc()}"
        )
        await safe_reply(message, ERROR_TEXT, reply_markup=ERROR_MARKUP)
        return

    if resp is None:
        # All retries failed - show error with action buttons
        logger.error(f"Agent returned None for {user_info} in {chat_type} {chat_id}")
        await safe_reply(message, ERROR_TEXT, reply_markup=ERROR_MARKUP)
    elif resp:
        await safe_reply(message, resp)
    else:
        logger.warning(f"Empty response from agent for {user_info} in {chat_type} {chat_id}")

    # Update user/group in DB (best-effort)
    try:
        if not message.sender_chat and message.from_user:
            from app.database.models import TelegramUser
            user = await read_db.get(TelegramUser, id=message.from_user.id)
            if not user:
                await write_db.add(TelegramUser(
                    id=message.from_user.id,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    username=message.from_user.username,
                ))
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            from app.database.models import TelegramGroup
            group = await read_db.get(TelegramGroup, id=message.chat.id)
            if not group:
                await write_db.add(TelegramGroup(
                    id=message.chat.id,
                    title=message.chat.title,
                    username=message.chat.username,
                ))
    except Exception as e:
        logger.warning(f"Failed to update DB for {chat_type} {chat_id}: {e}")
