"""Compatibility command for provider creation."""

from pyrogram import Client, filters, types


@Client.on_message(filters.command("add_provider"))  # type: ignore
async def add_provider_handler(client: Client, message: types.Message):
    """Direct users to the credential-safe button wizard."""
    del client
    await message.reply(
        "Use /providers → **➕ Add Provider**.\n\n"
        "The wizard deletes API-key input messages immediately and records you as the provider owner. "
        "For security, /add_provider <...> <api_key> is no longer accepted.",
        quote=True,
    )
