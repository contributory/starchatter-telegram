import asyncio

from app.ai.text import localize
from app.database.local import local_db
from pyrogram import Client, enums, filters, types

basic_buttons = [
    types.InlineKeyboardButton(text="Channel", url="https://t.me/starfall_org"),
    types.InlineKeyboardButton(text="Group", url="https://t.me/starfall_community"),
    types.InlineKeyboardButton(text="Discord", url="https://discord.gg/9WF54BSc4s"),
]


@Client.on_message(filters.command(["start", "help"]))  # type: ignore
async def start(client: Client, message: types.Message):
    """Handle start/help command"""
    markup = types.InlineKeyboardMarkup([[button for button in basic_buttons]])
    welcome_text = await localize(
        "Welcome to StarChatter.\n\nAvailable commands:\n\n"
        "/menu - Open main menu with buttons\n"
        "/image [prompt] - Generate an image (NSFW non-blocked).\n"
        "/poem [prompt] - Generate a poem.",
        user_id=message.from_user.id,
    )
    await message.reply(welcome_text, reply_markup=markup)
