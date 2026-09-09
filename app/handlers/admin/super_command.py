"""Admin panel handlers for /super command."""

from pyrogram import Client, enums, filters, types
from app.handlers.owner import is_user_owner
from app.handlers.admin.admin_callbacks import ADMIN_PANEL_TEXT, _build_admin_panel_keyboard


@Client.on_message(
    filters.command("super")
    & filters.create(lambda _, __, msg: is_user_owner(msg.from_user.id))  # type: ignore
)
async def super_command(client: Client, message: types.Message):
    """Show administrator panel with inline keyboard buttons."""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    await message.reply(
        ADMIN_PANEL_TEXT,
        reply_markup=_build_admin_panel_keyboard(),
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )
