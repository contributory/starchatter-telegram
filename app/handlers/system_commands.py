"""Public /start and /help command handlers."""

from app.ai.text import localize
from app.database.local import local_db
from pyrogram import Client, enums, filters, types


COMMUNITY_BUTTONS = [
    types.InlineKeyboardButton(text="Channel", url="https://t.me/starfall_org"),
    types.InlineKeyboardButton(text="Group", url="https://t.me/starfall_community"),
    types.InlineKeyboardButton(text="Discord", url="https://discord.gg/9WF54BSc4s"),
]


def _start_markup() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="🤖 Providers", callback_data="provider/list"
            ),
            types.InlineKeyboardButton(
                text="📱 Menu", callback_data="start/menu"
            ),
        ],
        COMMUNITY_BUTTONS,
    ])


def _help_markup() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="🤖 Providers", callback_data="provider/list"
            ),
            types.InlineKeyboardButton(
                text="📱 Menu", callback_data="start/menu"
            ),
        ],
        COMMUNITY_BUTTONS,
    ])


async def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    try:
        return await local_db.is_owner(user_id)
    except Exception:
        return False


async def _start_text(user_id: int) -> str:
    return await localize(
        "**Welcome to StarChatter ✨**\n\n"
        "Chat with AI, generate content, and connect OpenAI-compatible providers.\n\n"
        "**Get started**\n"
        "• `/providers` — Browse providers or add your own\n"
        "• `/chat` — Open chat controls\n"
        "• `/menu` — Open the main menu\n"
        "• `/help` — Show all available commands\n\n"
        "**Provider support**\n"
        "• Chat Completions\n"
        "• OpenAI Responses\n\n"
        "Anyone can browse providers. Providers you create remain yours: only you can reveal their API key, edit them, or delete them. "
        "For security, adding providers and viewing API keys is done in a private chat with the bot.",
        user_id=user_id,
    )


async def _help_text(user_id: int, is_admin: bool) -> str:
    text = (
        "**StarChatter Help**\n\n"
        "**Public commands**\n"
        "• `/start` — Welcome and quick start\n"
        "• `/help` — Show this help\n"
        "• `/menu` — Open the main menu\n"
        "• `/providers` — Browse providers and manage providers you created\n"
        "• `/chat` — Open chat controls\n"
        "• `/clear` — Clear the current chat session\n"
        "• `/image [prompt]` — Generate an image\n"
        "• `/poem [prompt]` — Generate a poem\n\n"
        "**Providers**\n"
        "Supported API modes: **Chat Completions** and **OpenAI Responses**.\n"
        "Use `/providers` → **➕ Add Provider** in a private chat to add one. "
        "You can reveal the API key, edit, or delete only providers you created; other users' provider credentials stay hidden.\n"
    )

    if is_admin:
        text += (
            "\n**Admin commands**\n"
            "• `/super` — Open the admin panel\n"
            "• `/models` — View/select models\n"
            "• `/setmodel` — Configure feature models\n"
            "• `/addmodel` — Add a model manually\n"
            "• `/mcp_servers` — Manage MCP servers\n"
            "• `/add_mcp` — Add an MCP server\n"
            "• `/toggle_mcp` — Enable/disable an MCP server\n"
            "• `/delete_mcp` — Delete an MCP server\n"
            "• `/update` — Update/restart the bot\n"
        )

    return await localize(text, user_id=user_id)


@Client.on_message(filters.command(["start", "help"]))  # type: ignore
async def start(client: Client, message: types.Message):
    """Handle public /start and /help commands."""
    del client
    if message.from_user is None:
        return

    await message.reply_chat_action(enums.ChatAction.TYPING)
    command = (message.command[0] if message.command else "start").lower()
    user_id = message.from_user.id

    if command == "help":
        text = await _help_text(user_id, await _is_admin(user_id))
        markup = _help_markup()
    else:
        text = await _start_text(user_id)
        markup = _start_markup()

    await message.reply(
        text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(filters.regex(r"^start/menu$"))
async def start_menu_callback(client: Client, callback_query: types.CallbackQuery):
    """Open the public main menu from /start or /help using edit_text."""
    del client
    from app.handlers.menu_command import MENU_TEXT, _build_menu_keyboard

    await callback_query.message.edit_text(
        MENU_TEXT,
        reply_markup=_build_menu_keyboard(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()
