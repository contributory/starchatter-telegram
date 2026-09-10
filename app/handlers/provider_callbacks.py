"""Provider callback handler for AI provider management."""

import logging

from pyrogram import Client, enums, filters, types
from sqlalchemy import select

from app.ai.base import get_provider_models
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import AIProvider
from app.handlers import flow_state
from app.handlers.owner import is_user_owner
from app.handlers.pagination import (
    ITEMS_PER_PAGE,
    create_models_keyboard,
    create_providers_keyboard,
)

logger = logging.getLogger(__name__)

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db
# In-memory state for the button-driven Add / Edit provider flows.
# { user_id: { "mode": "add"|"edit", "step": str, "chat_id": int,
#              "menu_msg_id": int, "provider_id": int | None, ... } }
_provider_flow: dict = {}


async def _get_provider(provider_id: int) -> AIProvider | None:
    result = await read_db.execute(
        select(AIProvider).where(AIProvider.id == provider_id)
    )
    return result.scalars().first()


@Client.on_callback_query(
    filters.regex(r"^provider/page/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_page_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle provider pagination callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    page = int(parts[2])
    await show_providers_list(client, callback_query.message, page, force_cloud=False)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/back$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle back to admin panel from providers list"""
    from app.handlers.admin.admin_callbacks import ADMIN_PANEL_TEXT, _build_admin_panel_keyboard
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    try:
        await callback_query.message.edit_text(
            ADMIN_PANEL_TEXT,
            reply_markup=_build_admin_panel_keyboard(),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/close$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_close_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle close providers list - delete current message only"""
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/list$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_list_handler(client: Client, callback_query: types.CallbackQuery):
    """Return from a provider's actions to the providers list."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    await show_providers_list(client, callback_query.message, 0, force_cloud=False)
    await callback_query.answer()


# ==================== Add Provider Flow ====================

@Client.on_callback_query(
    filters.regex(r"^provider/add$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_add_handler(client: Client, callback_query: types.CallbackQuery):
    """Start the Add Provider flow - ask for the provider name."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    _provider_flow[user_id] = {
        "mode": "add",
        "step": "name",
        "chat_id": chat_id,
        "menu_msg_id": callback_query.message.id,
    }
    # Ignore the user's next text messages in the chatbot listener.
    flow_state.start_flow(user_id, "provider_add")

    cancel_markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="❌ Cancel", callback_data="provider/add_cancel"
        )
    ]])

    try:
        await callback_query.message.edit_text(
            "**➕ Add Provider — Step 1/3**\n\n"
            "Please send the **provider name** (e.g. `openai`):",
            reply_markup=cancel_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/add_cancel$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_add_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    """Cancel the Add Provider flow."""
    user_id = callback_query.from_user.id
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    await show_providers_list(client, callback_query.message, 0, force_cloud=False)
    await callback_query.answer("Cancelled.")


# ==================== Edit Provider Flow ====================

@Client.on_callback_query(
    filters.regex(r"^provider/edit/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_edit_handler(client: Client, callback_query: types.CallbackQuery):
    """Show the Edit Provider menu."""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return
    await show_provider_edit_menu(client, callback_query.message, provider)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/edit_back/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_edit_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Back from the edit menu to provider actions."""
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return
    await show_provider_actions(client, callback_query.message, provider)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/edit_field/\d+/(name|url|api_key)$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_edit_field_handler(client: Client, callback_query: types.CallbackQuery):
    """Start editing a single provider field (name / url / api_key)."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])
    field = parts[3]

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    _provider_flow[user_id] = {
        "mode": "edit",
        "step": f"edit_{field}",
        "provider_id": provider_id,
        "chat_id": chat_id,
        "menu_msg_id": callback_query.message.id,
    }
    flow_state.start_flow(user_id, "provider_edit")

    current_map = {
        "name": f"Current name: `{provider.name}`",
        "url": f"Current URL: `{provider.base_url}`",
        "api_key": f"Current API Key: `{provider.api_key[:10]}...`",
    }
    prompt_map = {
        "name": "Send the **new provider name**:",
        "url": "Send the **new base URL** (must start with `http://` or `https://`):",
        "api_key": "Send the **new API key**:",
    }

    cancel_markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="❌ Cancel",
            callback_data=f"provider/edit_cancel/{provider_id}",
        )
    ]])

    try:
        await callback_query.message.edit_text(
            f"**✏️ Edit Provider — {field.replace('_', ' ').title()}**\n\n"
            f"{current_map[field]}\n\n{prompt_map[field]}",
            reply_markup=cancel_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/edit_cancel/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_edit_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    """Cancel an in-progress field edit and return to the provider actions."""
    user_id = callback_query.from_user.id
    provider_id = int(str(callback_query.data).split("/")[2])
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)

    provider = await _get_provider(provider_id)
    if provider:
        await show_provider_actions(client, callback_query.message, provider)
    await callback_query.answer("Cancelled.")


# ==================== Provider Flow Conversation (text input) ====================

@Client.on_message(
    filters.create(lambda _, __, m: (
        m.from_user is not None
        and is_user_owner(m.from_user.id)
        and m.from_user.id in _provider_flow
        and not (m.text or "").startswith("/")
    ))  # type: ignore
)
async def provider_flow_conversation_handler(client: Client, message: types.Message):
    """Handle step-by-step Add / Edit provider text input.

    Returns True to stop further handler propagation once the message has
    been consumed by the flow.
    """
    user_id = message.from_user.id
    state = _provider_flow.get(user_id)
    if not state:
        return

    text = (message.text or "").strip()
    if not text:
        return True

    chat_id = state["chat_id"]
    menu_msg_id = state["menu_msg_id"]
    mode = state["mode"]

    # Delete the admin's input message to keep the chat clean.
    try:
        await message.delete()
    except Exception:
        pass

    cancel_markup = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(
            text="❌ Cancel",
            callback_data=(
                "provider/add_cancel"
                if mode == "add"
                else f"provider/edit_cancel/{state.get('provider_id')}"
            ),
        )
    ]])

    # ---------- ADD FLOW ----------
    if mode == "add":
        step = state["step"]
        if step == "name":
            state["name"] = text
            state["step"] = "url"
            await _safe_edit(
                client, chat_id, menu_msg_id,
                "**➕ Add Provider — Step 2/3**\n\n"
                f"**Name:** `{text}`\n\n"
                "Now send the **base URL** (e.g. `https://api.openai.com/v1`):",
                cancel_markup,
            )
        elif step == "url":
            if not (text.startswith("http://") or text.startswith("https://")):
                await _safe_edit(
                    client, chat_id, menu_msg_id,
                    "**➕ Add Provider — Step 2/3**\n\n"
                    f"**Name:** `{state['name']}`\n\n"
                    "❌ Invalid URL. Must start with `http://` or `https://`.\n\n"
                    "Please send a valid URL:",
                    cancel_markup,
                )
                return True
            state["url"] = text
            state["step"] = "api_key"
            await _safe_edit(
                client, chat_id, menu_msg_id,
                "**➕ Add Provider — Step 3/3**\n\n"
                f"**Name:** `{state['name']}`\n"
                f"**URL:** `{text}`\n\n"
                "Finally, send the **API key**:",
                cancel_markup,
            )
        elif step == "api_key":
            await _finalize_add_provider(
                client, user_id, state, chat_id, menu_msg_id, api_key=text
            )
        return True

    # ---------- EDIT FLOW ----------
    if mode == "edit":
        provider_id = state["provider_id"]
        provider = await _get_provider(provider_id)
        if not provider:
            _provider_flow.pop(user_id, None)
            flow_state.end_flow(user_id)
            await _safe_edit(client, chat_id, menu_msg_id,
                             "**⚠️ Provider not found.**", None)
            return True

        step = state["step"]
        if step == "edit_name":
            provider.name = text
        elif step == "edit_url":
            if not (text.startswith("http://") or text.startswith("https://")):
                await _safe_edit(
                    client, chat_id, menu_msg_id,
                    "**✏️ Edit Provider — URL**\n\n"
                    "❌ Invalid URL. Must start with `http://` or `https://`.\n\n"
                    "Please send a valid URL:",
                    cancel_markup,
                )
                return True
            provider.base_url = text
        elif step == "edit_api_key":
            provider.api_key = text

        # Persist the change (cloud + local).
        try:
            await write_db.merge(provider)
        except Exception as e:
            logger.warning(f"Failed to update provider {provider_id}: {e}")

        _provider_flow.pop(user_id, None)
        flow_state.end_flow(user_id)

        # Return to the provider actions view.
        fresh = await _get_provider(provider_id)
        if fresh:
            await show_provider_actions(
                client, _EditProxy(client, chat_id, menu_msg_id), fresh
            )
        return True

    return True


async def _finalize_add_provider(
    client: Client,
    user_id: int,
    state: dict,
    chat_id: int,
    menu_msg_id: int,
    api_key: str,
):
    """Create the provider and refresh the providers list."""
    name = state["name"]
    url = state["url"]
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)

    try:
        provider = AIProvider(name=name, base_url=url, api_key=api_key)
        await write_db.add(provider)
        if await read_db.get_default_provider() is None:
            await write_db.set_default_provider(provider)
        note = f"✅ Provider `{name}` added!"
    except Exception as e:
        note = f"❌ Failed to add provider: `{e}`"

    menu_msg = await client.get_messages(chat_id, menu_msg_id)
    if menu_msg:
        await show_providers_list(client, menu_msg, 0, force_cloud=False)
    else:
        await _safe_edit(client, chat_id, menu_msg_id, note, None)

async def _safe_edit(
    client: Client,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None,
):
    """Edit a message by ids, ignoring errors."""
    try:
        await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass


class _EditProxy:
    """Minimal message-like object exposing edit_text() for helper functions.

    Used when we only have (chat_id, message_id) and want to reuse helpers
    such as show_provider_actions() that call ``message.edit_text``.
    """

    def __init__(self, client: Client, chat_id: int, message_id: int):
        self._client = client
        self.chat = None
        self.chat_id = chat_id
        self.id = message_id
        self.text = None
        self.reply_markup = None

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        await self._client.edit_message_text(
            chat_id=self.chat_id,
            message_id=self.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


@Client.on_callback_query(
    filters.regex(r"^provider/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_number_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle provider number selection callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_num = int(parts[1])
    result = await read_db.execute(select(AIProvider))
    providers = result.scalars().all()

    if 1 <= provider_num <= len(providers):
        provider = providers[provider_num - 1]
        await show_provider_actions(
            client, callback_query.message, provider, force_cloud=False
        )
    else:
        await callback_query.answer("Invalid provider number!", show_alert=True)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/select/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_select_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle provider selection callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    await write_db.set_default_provider(provider)
    await callback_query.answer(
        f"✅ Provider `{provider.name}` is now default!", show_alert=True
    )
    # Refresh provider actions view
    await show_provider_actions(client, callback_query.message, provider, force_cloud=False)


@Client.on_callback_query(
    filters.regex(r"^provider/delete/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_delete_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle provider delete callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    await write_db.delete(provider)
    await callback_query.answer(f"🗑️ Provider `{provider.name}` deleted!", show_alert=True)
    await show_providers_list(client, callback_query.message, 0, force_cloud=False)


@Client.on_callback_query(
    filters.regex(r"^provider/models_/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_models_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle initial provider models callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    await show_provider_models(
        client, callback_query.message, provider.id, provider.name, 0
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/models_/\d+/page/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_models_page_handler(
    client: Client, callback_query: types.CallbackQuery
):
    """Handle provider models pagination callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])
    page = int(parts[4])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    await show_provider_models(
        client, callback_query.message, provider.id, provider.name, page
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/models_/\d+/back$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_models_back_handler(
    client: Client, callback_query: types.CallbackQuery
):
    """Handle back from models to provider actions callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    await show_provider_actions(
        client, callback_query.message, provider, force_cloud=False
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider_models_select/\d+/\d+$")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def provider_models_select_handler(
    client: Client, callback_query: types.CallbackQuery
):
    """Handle provider model selection callback"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[1])
    model_index = int(parts[2])

    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found!", show_alert=True)
        return

    all_models = await get_provider_models(provider=provider)

    if not all_models:
        await callback_query.answer("No models available!", show_alert=True)
        return

    actual_model_index = model_index - 1
    selected_model = all_models[actual_model_index]
    await write_db.set_default_model("chat", provider.name, selected_model)
    await write_db.set_default_provider(provider)
    await callback_query.answer(f"✅ Selected model: `{selected_model}`", show_alert=True)
    await show_provider_actions(client, callback_query.message, provider)
    await callback_query.answer()


# ==================== Helper Functions ====================

async def show_providers_list(
    client: Client, message: types.Message, page: int = 0, force_cloud: bool = False
):
    """Display providers list with pagination using edit_text."""
    result = await read_db.execute(select(AIProvider))
    providers = result.scalars().all()
    default_provider = await (
        cloud_db.get_default_provider()
        if force_cloud
        else read_db.get_default_provider()
    )

    add_button_row = [
        types.InlineKeyboardButton(
            text="➕ Add Provider", callback_data="provider/add"
        )
    ]

    if not providers:
        markup = types.InlineKeyboardMarkup([
            [add_button_row[0]],
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/back")],
        ])
        try:
            await message.edit_text(
                "**🤖 AI Providers**\n\n"
                "No providers yet.\n\n"
                "Tap **➕ Add Provider** to add one, or use\n"
                "`/add_provider <name> <base_url> <api_key>`.",
                reply_markup=markup,
            )
        except Exception:
            pass
        return

    providers_list = [(p.id, p.name) for p in providers]
    total_pages = max(1, (len(providers_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(providers_list))
    page_providers = providers_list[start_idx:end_idx]

    markup = create_providers_keyboard(
        providers=page_providers,
        page=page,
        callback_prefix="provider",
        total_pages=total_pages,
        back_callback="provider/back",
    )
    # Insert "➕ Add Provider" button at the top
    markup.inline_keyboard.insert(0, [add_button_row[0]])

    start_num = page * ITEMS_PER_PAGE + 1
    provider_names = []
    for i, (provider_id, provider_name) in enumerate(page_providers):
        num = start_num + i
        is_default = default_provider and provider_id == default_provider.id
        prefix = "⭐ " if is_default else ""
        provider_names.append(f"`{num}`. {prefix}`{provider_name}`")

    providers_text = "\n".join(provider_names)
    new_text = (
        f"**🤖 AI Providers** (Page {page + 1}/{total_pages})\n\n"
        f"{providers_text}\n\n"
        f"Tap a number to select, or ➕ to add new provider."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass


async def show_provider_actions(
    client: Client,
    message: types.Message,
    provider: AIProvider,
    force_cloud: bool = False,
):
    """Display action buttons for a specific provider using edit_text."""
    default_provider = await (
        cloud_db.get_default_provider()
        if force_cloud
        else read_db.get_default_provider()
    )

    buttons = [
        [
            types.InlineKeyboardButton(
                text=f"🔹 {provider.name}", callback_data="noop"
            )
        ],
        [
            types.InlineKeyboardButton(
                text="✅ Select", callback_data=f"provider/select/{provider.id}"
            ),
            types.InlineKeyboardButton(
                text="✏️ Edit", callback_data=f"provider/edit/{provider.id}"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="🤖 Models", callback_data=f"provider/models_/{provider.id}"
            ),
            types.InlineKeyboardButton(
                text="🗑️ Delete", callback_data=f"provider/delete/{provider.id}"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⬅️ Back to Providers", callback_data="provider/list"
            ),
        ],
    ]
    markup = types.InlineKeyboardMarkup(buttons)

    is_default = default_provider and provider.id == default_provider.id
    status = " ⭐ (Default)" if is_default else ""

    new_text = (
        f"**🤖 Provider: {provider.name}**{status}\n\n"
        f"**URL:** `{provider.base_url}`\n"
        f"**API Key:** `{provider.api_key[:10]}...`\n\n"
        f"Use buttons below to manage this provider."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass


async def show_provider_edit_menu(
    client: Client, message: types.Message, provider: AIProvider
):
    """Display the Edit Provider menu with per-field buttons."""
    buttons = [
        [types.InlineKeyboardButton(
            text=f"🔹 Editing: {provider.name}", callback_data="noop"
        )],
        [
            types.InlineKeyboardButton(
                text="📝 Name", callback_data=f"provider/edit_field/{provider.id}/name"
            ),
            types.InlineKeyboardButton(
                text="🔗 URL", callback_data=f"provider/edit_field/{provider.id}/url"
            ),
        ],
        [types.InlineKeyboardButton(
            text="🔑 API Key", callback_data=f"provider/edit_field/{provider.id}/api_key"
        )],
        [types.InlineKeyboardButton(
            text="⬅️ Back", callback_data=f"provider/edit_back/{provider.id}"
        )],
    ]
    markup = types.InlineKeyboardMarkup(buttons)

    new_text = (
        f"**✏️ Edit Provider: {provider.name}**\n\n"
        f"**URL:** `{provider.base_url}`\n"
        f"**API Key:** `{provider.api_key[:10]}...`\n\n"
        f"Choose a field to edit."
    )
    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass


async def show_provider_models(
    client: Client,
    message: types.Message,
    provider_id: int,
    provider_name: str,
    page: int,
):
    """Display models list of a provider with pagination using edit_text."""
    provider_object = await _get_provider(provider_id)

    if not provider_object:
        buttons = [
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/back")],
        ]
        markup = types.InlineKeyboardMarkup(buttons)
        try:
            await message.edit_text(
                "**⚠️ Error**\n\nProvider not found!",
                reply_markup=markup,
            )
        except Exception:
            pass
        return

    all_models = await get_provider_models(provider=provider_object)

    if not all_models:
        buttons = [
            [types.InlineKeyboardButton(
                text="⬅️ Back", callback_data=f"provider/models_/{provider_id}/back"
            )]
        ]
        markup = types.InlineKeyboardMarkup(buttons)
        try:
            await message.edit_text(
                f"**🤖 Models for {provider_name}**\n\n"
                f"No models available.\n\n"
                f"Please check your provider settings or API connection.",
                reply_markup=markup,
            )
        except Exception:
            pass
        return

    total_pages = max(1, (len(all_models) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(all_models))
    page_models = all_models[start_idx:end_idx]

    markup = create_models_keyboard(
        models=page_models,
        page=page,
        callback_prefix=f"provider_models_select/{provider_id}",
        total_pages=total_pages,
        back_callback=f"provider/models_/{provider_id}/back",
    )

    start_num = page * ITEMS_PER_PAGE + 1
    model_names = []
    for i, model in enumerate(page_models):
        num = start_num + i
        model_names.append(f"`{num}`. `{model}`")

    models_text = "\n".join(model_names)

    new_text = (
        f"**🤖 Models for {provider_name}** (Page {page + 1}/{total_pages})\n\n"
        f"{models_text}\n\n"
        f"Tap a number to select model."
    )

    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass
