"""Public /providers command."""

from pyrogram import Client, enums, filters, types

from app.handlers import flow_state
from app.handlers.provider_callbacks import build_providers_list


@Client.on_message(filters.command("providers"))  # type: ignore
async def providers_handler(client: Client, message: types.Message, page: int = 0):
    """Let any Telegram user browse and add AI providers."""
    del client
    if message.from_user is None:
        await message.reply(
            "Provider management is unavailable for anonymous sender identities.",
            quote=True,
        )
        return

    user_id = message.from_user.id
    flow_state.end_flow(user_id)
    text, markup = await build_providers_list(user_id, page)
    await message.reply_chat_action(enums.ChatAction.TYPING)
    await message.reply(
        text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )
