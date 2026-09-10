"""Command handlers for AI provider and model management."""

from app.handlers.owner import is_user_owner
from app.handlers.pagination import (
    ITEMS_PER_PAGE,
    create_providers_keyboard,
)
from pyrogram import Client, enums, filters, types
from sqlalchemy import select

from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import AIProvider

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db


def _add_provider_button() -> types.InlineKeyboardButton:
    """The '➕ Add Provider' button shown at the top of the providers list."""
    return types.InlineKeyboardButton(
        text="➕ Add Provider", callback_data="provider/add"
    )


@Client.on_message(
    filters.command("providers")
    & filters.create(lambda _, __, m: is_user_owner(m.from_user.id))  # type: ignore
)
async def providers_handler(client: Client, message: types.Message, page: int = 0):
    """List AI providers with pagination"""
    await message.reply_chat_action(enums.ChatAction.TYPING)

    result = await read_db.execute(select(AIProvider))
    providers = result.scalars().all()
    default_provider = await read_db.get_default_provider()

    if not providers:
        markup = types.InlineKeyboardMarkup([
            [_add_provider_button()],
        ])
        await message.reply(
            "**🤖 AI Providers**\n\n"
            "No providers yet.\n\n"
            "Tap **➕ Add Provider** to add one, or use\n"
            "`/add_provider <name> <base_url> <api_key>`",
            reply_markup=markup,
            quote=True,
        )
        return

    # Prepare providers list with (id, name) tuples
    providers_list = [(p.id, p.name) for p in providers]

    # Calculate pagination
    total_pages = max(1, (len(providers_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(providers_list))
    page_providers = providers_list[start_idx:end_idx]

    # Create keyboard with numbered buttons
    markup = create_providers_keyboard(
        providers=page_providers,
        page=page,
        callback_prefix="provider",
        total_pages=total_pages,
    )
    # Insert "➕ Add Provider" button at the top
    markup.inline_keyboard.insert(0, [_add_provider_button()])

    # Build message with provider names and numbers
    start_num = page * ITEMS_PER_PAGE + 1
    provider_names = []
    for i, (provider_id, provider_name) in enumerate(page_providers):
        num = start_num + i
        is_default = default_provider and provider_id == default_provider.id
        prefix = "⭐ " if is_default else ""
        provider_names.append(f"`{num}`. {prefix}`{provider_name}`")

    providers_text = "\n".join(provider_names)

    await message.reply(
        f"**AI Providers** (Page {page + 1}/{total_pages})\n\n"
        f"{providers_text}\n\n"
        f"Tap a number to select, or ➕ to add new provider.",
        reply_markup=markup,
        quote=True,
    )
