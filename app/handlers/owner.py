"""Owner authentication handler"""
from app.config import OWNER_PASSWORD
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import TelegramUser
from sqlalchemy import select
from sqlalchemy.orm import Session
from pyrogram import Client, enums, filters, types

db = cloud_db


def verify_password(password: str) -> bool:
    """Verify password (plain text)"""
    if not OWNER_PASSWORD:
        return False
    return password == OWNER_PASSWORD


def is_user_owner(user_id: int) -> bool:
    """Check owner status synchronously for Pyrogram filter predicates.

    Filters run on the dispatcher's active event-loop thread, so this helper
    must never call ``run_until_complete``. Owner data is mirrored to the
    local SQLite database at startup; use a short independent SQLAlchemy
    session for the tiny lookup instead.
    """
    try:
        local_db.init_db()
        with Session(local_db.engine) as session:
            value = session.execute(
                select(TelegramUser.is_owner).where(TelegramUser.id == user_id)
            ).scalar_one_or_none()
            return bool(value)
    except Exception:
        return False


async def is_user_owner_async(user_id: int) -> bool:
    """Check owner status from async handlers without nesting event loops."""
    return await local_db.is_owner(user_id)


@Client.on_message(filters.command("owner") & filters.private)  # type: ignore
async def owner_handler(client: Client, message: types.Message):
    """Verify owner privilege with password"""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    args = message.text.split()
    
    if len(args) < 2:
        await message.reply(
            "**Owner Verification**\n\n"
            "Enter password to verify:\n"
            "/owner <password>",
            quote=True,
        )
        return
    
    password = args[1]
    
    if verify_password(password):
        # Add user to owners list (write via cloud)
        user = message.from_user
        await db.add_owner(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        
        await message.reply(
            "✅ **Verification successful!**\n\n"
            "You have been added to the owners list.",
            quote=True,
        )
    else:
        await message.reply(
            "❌ **Verification failed!**\n\n"
            "Password is incorrect.",
            quote=True,
        )
