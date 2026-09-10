import logging
import os
import tempfile
import traceback
from datetime import datetime
from typing import Dict, Optional, Set

from app.ai.agent import AIAgent
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.handlers.owner import is_user_owner
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

# Store the most recent short error detail per chat (fallback if no file exists).
_last_errors: Dict[int, str] = {}

# Map a chat -> temporary file holding the full error detail for reporting.
_last_error_files: Dict[int, str] = {}

# Track error messages whose report has already been sent (button disabled).
_reported_messages: Set[int] = set()

# Map a report message id (sent to admin) -> original chat where the error occurred.
_report_map: Dict[int, int] = {}


def _save_error_file(chat_id: int, error_text: str) -> Optional[str]:
    """Write the full error detail to a temporary file and return its path."""
    try:
        fd, path = tempfile.mkstemp(
            prefix=f"starchatter_err_{chat_id}_",
            suffix=".txt",
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("Starchatter Bot Error Report\n")
            f.write(f"Chat: {chat_id}\n")
            f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(error_text or "(no error detail)")
        return path
    except Exception as e:
        logger.error(f"Failed to write error file for chat {chat_id}: {e}")
        return None


def _record_error(chat_id: int, error_text: str) -> None:
    """Remember the error detail and save the full text to a temporary file."""
    detail = (error_text or "").strip()
    # Keep a short version in memory as a fallback.
    _last_errors[chat_id] = detail[:3500]

    # Save the FULL untruncated error to a temp file for reporting.
    path = _save_error_file(chat_id, error_text or "(no error detail)")
    if path:
        # Replace any previously saved file for this chat.
        old = _last_error_files.get(chat_id)
        if old and os.path.isfile(old):
            try:
                os.remove(old)
            except Exception:
                pass
        _last_error_files[chat_id] = path


def _is_error_report_reply(_, __, message) -> bool:
    """True when a private message replies to one of our sent error reports."""
    reply = getattr(message, "reply_to_message", None)
    return bool(reply and reply.id in _report_map)


ERROR_MARKUP = types.InlineKeyboardMarkup([
    [
        types.InlineKeyboardButton(text="🔄 Reset Chat", callback_data="chat:reset:confirm"),
        types.InlineKeyboardButton(text="🤖 Models", callback_data="admin:models"),
    ],
    [
        types.InlineKeyboardButton(text="📤 Report Error", callback_data="error:send"),
    ],
])


def _sent_error_markup() -> types.InlineKeyboardMarkup:
    """Markup shown after the error report has been sent (button is disabled)."""
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(text="🔄 Reset Chat", callback_data="chat:reset:confirm"),
            types.InlineKeyboardButton(text="🤖 Models", callback_data="admin:models"),
        ],
        [
            # Routed to the noop handler so it can't trigger a re-send.
            types.InlineKeyboardButton(text="✅ Reported", callback_data="noop:error_sent"),
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
    & ~filters.create(_is_error_report_reply)  # type: ignore
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
        _record_error(
            chat_id,
            f"[AIAgent.create] failed in {chat_type} {chat_id}\n{traceback.format_exc()}",
        )
        await safe_reply(message, ERROR_TEXT, reply_markup=ERROR_MARKUP)
        return

    try:
        resp = await agent.run_chat(client, message)
    except Exception as e:
        logger.error(
            f"Agent.run_chat failed for {user_info} in {chat_type} {chat_id}: "
            f"{e}\n{traceback.format_exc()}"
        )
        _record_error(
            chat_id,
            f"[Agent.run_chat] failed for {user_info} in {chat_type} {chat_id}\n"
            f"{traceback.format_exc()}",
        )
        await safe_reply(message, ERROR_TEXT, reply_markup=ERROR_MARKUP)
        return

    if resp is None:
        # All retries failed - show error with action buttons
        logger.error(f"Agent returned None for {user_info} in {chat_type} {chat_id}")
        # Include the FULL error captured by the agent (API body, traceback...).
        agent_full_error = getattr(agent, "last_error_text", "") or ""
        _record_error(
            chat_id,
            f"[Agent] returned None for {user_info} in {chat_type} {chat_id}. "
            "All retries were exhausted.\n\n"
            f"{agent_full_error}",
        )
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


async def _send_error_report(client: Client, chat_id: int) -> bool:
    """Send the full error file to the bot admins' private chats.

    Sends the whole temporary error file as a document. If no file is
    available, falls back to an inline message with the short error detail.

    Returns True if at least one admin received the report.
    Also records a mapping so that an admin replying to the report message
    routes that reply back to the chat where the error occurred.
    """
    error_text = _last_errors.get(chat_id)
    file_path = _last_error_files.get(chat_id)
    if file_path and not os.path.isfile(file_path):
        file_path = None

    sent = False
    try:
        owners = await cloud_db.get_all_owners()
    except Exception as e:
        logger.error(f"Failed to fetch owners: {e}")
        owners = []

    file_name = os.path.basename(file_path) if file_path else f"error_{chat_id}.txt"

    for owner in owners or []:
        try:
            if file_path:
                # Send the ENTIRE error file to the admin.
                sent_msg = await client.send_document(
                    owner.id,
                    file_path,
                    file_name=file_name,
                    caption=(
                        "⚠️ **Bot Error Report**\n\n"
                        f"**Chat:** `{chat_id}`\n\n"
                        "The full error is attached below.\n\n"
                        "__Reply to this message to send a response to that chat.__"
                    ),
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            else:
                # Fallback: no file available - send short detail as text.
                content = error_text or "No detailed error message was recorded."
                report = (
                    "⚠️ **Bot Error Report**\n\n"
                    f"**Chat:** `{chat_id}`\n\n"
                    f"```text\n{content}\n```\n\n"
                    "__Reply to this message to send a response to that chat.__"
                )
                sent_msg = await client.send_message(
                    owner.id,
                    report,
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            # Remember the source chat so an admin reply can be routed back.
            _report_map[sent_msg.id] = chat_id
            sent = True
        except Exception as e:
            logger.error(f"Failed to send error report to owner {owner.id}: {e}")

    # Clean up the temp file once at least one admin received the report.
    if sent and file_path:
        _last_error_files.pop(chat_id, None)
        try:
            os.remove(file_path)
        except Exception:
            pass

    return sent


@Client.on_callback_query(filters.regex(r"^error:send$"))
async def send_error_callback(client: Client, callback_query: types.CallbackQuery):
    """Anyone can send the report once; afterwards the button is disabled."""
    message = callback_query.message
    chat_id = message.chat.id

    # Prevent sending the same report more than once (button becomes disabled).
    if message.id in _reported_messages:
        await callback_query.answer("Error report already sent.", show_alert=True)
        try:
            await message.edit_reply_markup(_sent_error_markup())
        except Exception:
            pass
        return

    _reported_messages.add(message.id)

    sent = await _send_error_report(client, chat_id)
    if sent:
        await callback_query.answer("✅ Error reported.")
        # Disable the button so it can't be pressed / re-sent again.
        try:
            await message.edit_reply_markup(_sent_error_markup())
        except Exception:
            pass
    else:
        # Sending failed - keep the button active so the user can retry.
        _reported_messages.discard(message.id)
        await callback_query.answer("❌ Could not send the error report.", show_alert=True)


@Client.on_message(
    filters.private
    & filters.incoming
    & ~filters.me  # type: ignore
    & filters.create(_is_error_report_reply)  # type: ignore
    & filters.create(lambda _, __, msg: is_user_owner(msg.from_user.id) if msg.from_user else False)  # type: ignore
)
async def admin_error_reply_handler(client: Client, message: types.Message):
    """Route an admin's reply to the error report back to the affected chat."""
    reply = message.reply_to_message
    if not reply:
        return

    target_chat_id = _report_map.get(reply.id)
    if target_chat_id is None:
        return

    admin_note = "👮‍♂️ **Admin response:**"

    try:
        text = message.text or message.caption or ""
        if text:
            body = f"{admin_note}\n\n{text}"
            await client.send_message(
                target_chat_id,
                body,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        else:
            # Non-text reply (media, sticker, ...) - copy it with the admin note as caption.
            caption = message.caption or ""
            new_caption = f"{admin_note}\n\n{caption}" if caption else admin_note
            await client.copy_message(
                target_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.id,
                caption=new_caption,
            )
        await message.reply("✅ Your response was sent to the chat.", quote=True)
    except Exception as e:
        logger.error(f"Failed to forward admin reply to chat {target_chat_id}: {e}")
        try:
            await message.reply(
                "❌ Could not send the response to the chat.",
                quote=True,
            )
        except Exception:
            pass
