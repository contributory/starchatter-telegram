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


def escape_markdown(text: str) -> str:
    """Escape special markdown characters to prevent parsing errors"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def safe_reply(message: types.Message, text: str, **kwargs):
    """Safely reply to a message, falling back to plain text if markdown fails"""
    # First try with markdown
    try:
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await message.reply(
                    text[i : i + 4000],
                    quote=True,
                    parse_mode=enums.ParseMode.MARKDOWN,
                    **kwargs,
                )
        else:
            await message.reply(
                text,
                quote=True,
                parse_mode=enums.ParseMode.MARKDOWN,
                **kwargs,
            )
        return True
    except BadRequest as e:
        error_str = str(e).lower()
        # If it's a markdown parsing error, retry without markdown
        if 'can\'t parse' in error_str or 'entities' in error_str or 'markdown' in error_str:
            logger.warning(f"Markdown parsing failed, sending plain text: {e}")
            try:
                if len(text) > 4000:
                    for i in range(0, len(text), 4000):
                        await message.reply(
                            text[i : i + 4000],
                            quote=True,
                            **kwargs,
                        )
                else:
                    await message.reply(
                        text,
                        quote=True,
                        **kwargs,
                    )
                return True
            except Exception as inner_e:
                logger.error(f"Plain text reply also failed: {inner_e}")
                return False
        else:
            logger.error(f"BadRequest error: {e}")
            return False
    except MessageNotModified:
        # Message was not modified, which is fine
        return True
    except Exception as e:
        logger.error(f"Unexpected error while replying: {e}")
        return False


@Client.on_message(
    (filters.mentioned & ~filters.new_chat_members | filters.private)
    & filters.incoming
    & ~filters.create(lambda _, __, m: m.text and m.text.startswith("/"))  # type: ignore
)
async def chatbot_handler(client: Client, message: types.Message):
    """Process chatbot message with improved error handling and logging"""
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
            "⚠️ Bot chưa được cấu hình AI provider. Vui lòng liên hệ admin."
        )
        return
    except Exception as e:
        logger.error(f"Unexpected error creating AIAgent: {e}\n{traceback.format_exc()}")
        await safe_reply(
            message,
            "⚠️ Đã xảy ra lỗi khi khởi tạo bot. Vui lòng thử lại sau."
        )
        return

    try:
        resp = await agent.run_chat(client, message)
    except Exception as e:
        logger.error(
            f"Agent.run_chat failed for {user_info} in {chat_type} {chat_id}: {e}\n"
            f"{traceback.format_exc()}"
        )
        await safe_reply(
            message,
            "⚠️ Xin lỗi, tôi đang gặp vấn đề. Vui lòng thử lại sau."
        )
        return
    
    if resp:
        success = await safe_reply(message, resp)
        if not success:
            logger.error(f"Failed to send response to {user_info} in {chat_type} {chat_id}")
    else:
        logger.warning(f"Empty response from agent for {user_info} in {chat_type} {chat_id}")

    # Update user/group in database (non-blocking, best-effort)
    try:
        if not message.sender_chat and message.from_user:
            from app.database.models import TelegramUser

            user = await read_db.get(TelegramUser, id=message.from_user.id)
            if not user:
                await write_db.add(
                    TelegramUser(
                        id=message.from_user.id,
                        first_name=message.from_user.first_name,
                        last_name=message.from_user.last_name,
                        username=message.from_user.username,
                    )
                )
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            from app.database.models import TelegramGroup

            group = await read_db.get(TelegramGroup, id=message.chat.id)
            if not group:
                await write_db.add(
                    TelegramGroup(
                        id=message.chat.id,
                        title=message.chat.title,
                        username=message.chat.username,
                    )
                )
    except Exception as e:
        logger.warning(f"Failed to update database for {chat_type} {chat_id}: {e}")
