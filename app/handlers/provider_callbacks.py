"""Provider callback handlers with per-user ownership enforcement."""

from __future__ import annotations

import logging

from pyrogram import Client, enums, filters, types
from sqlalchemy import select

from app.ai.base import get_provider_models
from app.ai.provider_types import (
    PROVIDER_CHAT_COMPLETIONS,
    PROVIDER_OPENAI_RESPONSES,
    provider_type_label,
)
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import AIProvider
from app.handlers import flow_state
from app.handlers.pagination import ITEMS_PER_PAGE, create_providers_keyboard

logger = logging.getLogger(__name__)

write_db = cloud_db
read_db = local_db

# {user_id: {mode, step, chat_id, menu_msg_id, ...}}
_provider_flow: dict[int, dict] = {}


async def _get_provider(provider_id: int) -> AIProvider | None:
    result = await read_db.execute(
        select(AIProvider).where(AIProvider.id == provider_id)
    )
    return result.scalars().first()


async def _all_providers() -> list[AIProvider]:
    result = await read_db.execute(select(AIProvider).order_by(AIProvider.id))
    return list(result.scalars().all())


def _is_provider_owner(provider: AIProvider, user_id: int) -> bool:
    return provider.created_by_user_id is not None and provider.created_by_user_id == user_id


async def _can_manage_provider(provider: AIProvider, user_id: int) -> bool:
    """User-created providers are manageable only by their creator.

    Providers created before ownership tracking have NULL owner and remain
    manageable by bot admins so legacy configuration never becomes orphaned.
    """
    if provider.created_by_user_id is not None:
        return provider.created_by_user_id == user_id
    return await read_db.is_owner(user_id)


async def _is_bot_admin(user_id: int) -> bool:
    return await read_db.is_owner(user_id)


def _masked_key(api_key: str) -> str:
    if not api_key:
        return "Not set"
    if len(api_key) <= 4:
        return "••••"
    return f"••••••••{api_key[-4:]}"


def _add_nav(back_callback: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback)],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="provider/add_cancel")],
    ])


def _type_markup() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(
            text="💬 Chat Completions",
            callback_data=f"provider/add_type/{PROVIDER_CHAT_COMPLETIONS}",
        )],
        [types.InlineKeyboardButton(
            text="⚡ OpenAI Responses",
            callback_data=f"provider/add_type/{PROVIDER_OPENAI_RESPONSES}",
        )],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/list")],
    ])


async def _safe_edit(
    client: Client,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None,
):
    try:
        await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.debug("Provider menu edit failed: %s", exc)


class _EditProxy:
    def __init__(self, client: Client, chat_id: int, message_id: int):
        self._client = client
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


async def _show_add_name(client: Client, state: dict) -> None:
    state["step"] = "name"
    await _safe_edit(
        client,
        state["chat_id"],
        state["menu_msg_id"],
        "**➕ Add Provider — Name (2/4)**\n\n"
        f"**Type:** `{provider_type_label(state['provider_type'])}`\n\n"
        "Send a unique **provider name** (for example `openai-main`):",
        _add_nav("provider/add"),
    )


async def _show_add_url(client: Client, state: dict) -> None:
    state["step"] = "url"
    await _safe_edit(
        client,
        state["chat_id"],
        state["menu_msg_id"],
        "**➕ Add Provider — Base URL (3/4)**\n\n"
        f"**Type:** `{provider_type_label(state['provider_type'])}`\n"
        f"**Name:** `{state['name']}`\n\n"
        "Send the OpenAI-compatible **base URL** "
        "(for example `https://api.openai.com/v1`):",
        _add_nav("provider/add_back/name"),
    )


async def _show_add_api_key(client: Client, state: dict) -> None:
    state["step"] = "api_key"
    await _safe_edit(
        client,
        state["chat_id"],
        state["menu_msg_id"],
        "**➕ Add Provider — API Key (4/4)**\n\n"
        f"**Type:** `{provider_type_label(state['provider_type'])}`\n"
        f"**Name:** `{state['name']}`\n"
        f"**URL:** `{state['url']}`\n\n"
        "Send the **API key**. Your input message will be deleted immediately.",
        _add_nav("provider/add_back/url"),
    )


# ==================== List navigation ====================

@Client.on_callback_query(filters.regex(r"^provider/page/\d+$"))
async def provider_page_handler(client: Client, callback_query: types.CallbackQuery):
    page = int(str(callback_query.data).split("/")[2])
    await show_providers_list(
        client, callback_query.message, page, viewer_user_id=callback_query.from_user.id
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/list$"))
async def provider_list_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    await show_providers_list(client, callback_query.message, 0, viewer_user_id=user_id)
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/back$"))
async def provider_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Return to the public main menu."""
    from app.handlers.menu_command import MENU_TEXT, _build_menu_keyboard

    user_id = callback_query.from_user.id
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    await callback_query.message.edit_text(
        MENU_TEXT,
        reply_markup=_build_menu_keyboard(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/close$"))
async def provider_close_handler(client: Client, callback_query: types.CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


# ==================== Add Provider ====================

@Client.on_callback_query(filters.regex(r"^provider/add$"))
async def provider_add_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "For safety, add providers in a private chat with the bot so API keys cannot leak.",
            show_alert=True,
        )
        return
    _provider_flow[user_id] = {
        "mode": "add",
        "step": "type",
        "chat_id": callback_query.message.chat.id,
        "menu_msg_id": callback_query.message.id,
    }
    flow_state.start_flow(user_id, "provider_add")
    await callback_query.message.edit_text(
        "**➕ Add Provider — Type (1/4)**\n\n"
        "Choose the API mode supported by this provider:\n\n"
        "💬 **Chat Completions** — `/chat/completions`\n"
        "⚡ **OpenAI Responses** — `/responses`",
        reply_markup=_type_markup(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/add_type/(chat_completions|openai_responses)$")
)
async def provider_add_type_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    state = _provider_flow.get(user_id)
    if not state or state.get("mode") != "add":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    state["provider_type"] = str(callback_query.data).rsplit("/", 1)[-1]
    await _show_add_name(client, state)
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/add_back/(name|url)$"))
async def provider_add_back_handler(client: Client, callback_query: types.CallbackQuery):
    state = _provider_flow.get(callback_query.from_user.id)
    if not state or state.get("mode") != "add":
        await callback_query.answer("Session expired.", show_alert=True)
        return
    target = str(callback_query.data).rsplit("/", 1)[-1]
    if target == "name":
        await _show_add_name(client, state)
    else:
        await _show_add_url(client, state)
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/add_cancel$"))
async def provider_add_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    await show_providers_list(client, callback_query.message, 0, viewer_user_id=user_id)
    await callback_query.answer("Cancelled.")


# ==================== Edit Provider ====================

@Client.on_callback_query(filters.regex(r"^provider/edit/\d+$"))
async def provider_edit_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, callback_query.from_user.id):
        await callback_query.answer("You can only edit providers you created.", show_alert=True)
        return
    await show_provider_edit_menu(
        client, callback_query.message, provider, callback_query.from_user.id
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/edit_back/\d+$"))
async def provider_edit_back_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    await show_provider_actions(
        client, callback_query.message, provider, callback_query.from_user.id
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/edit_field/\d+/(name|url|api_key)$")
)
async def provider_edit_field_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])
    field = parts[3]
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, user_id):
        await callback_query.answer("You can only edit providers you created.", show_alert=True)
        return
    if field == "api_key" and callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "For safety, edit API keys in a private chat with the bot.",
            show_alert=True,
        )
        return

    _provider_flow[user_id] = {
        "mode": "edit",
        "step": f"edit_{field}",
        "provider_id": provider_id,
        "chat_id": callback_query.message.chat.id,
        "menu_msg_id": callback_query.message.id,
    }
    flow_state.start_flow(user_id, "provider_edit")

    current = {
        "name": f"Current name: `{provider.name}`",
        "url": f"Current URL: `{provider.base_url}`",
        "api_key": f"Current API Key: `{_masked_key(provider.api_key)}`",
    }[field]
    prompt = {
        "name": "Send the **new provider name**:",
        "url": "Send the **new base URL**:",
        "api_key": "Send the **new API key**. The input message will be deleted immediately:",
    }[field]
    await callback_query.message.edit_text(
        f"**✏️ Edit Provider — {field.replace('_', ' ').title()}**\n\n"
        f"{current}\n\n{prompt}",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(
                text="⬅️ Back", callback_data=f"provider/edit_cancel/{provider_id}"
            )],
        ]),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/edit_type/\d+$"))
async def provider_edit_type_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, callback_query.from_user.id):
        await callback_query.answer("You can only edit providers you created.", show_alert=True)
        return
    markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton(
            text="💬 Chat Completions",
            callback_data=f"provider/set_type/{provider_id}/{PROVIDER_CHAT_COMPLETIONS}",
        )],
        [types.InlineKeyboardButton(
            text="⚡ OpenAI Responses",
            callback_data=f"provider/set_type/{provider_id}/{PROVIDER_OPENAI_RESPONSES}",
        )],
        [types.InlineKeyboardButton(
            text="⬅️ Back", callback_data=f"provider/edit/{provider_id}"
        )],
    ])
    await callback_query.message.edit_text(
        "**✏️ Edit Provider — Type**\n\n"
        f"Current: `{provider_type_label(provider.provider_type)}`\n\n"
        "Choose the new API mode:",
        reply_markup=markup,
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"^provider/set_type/\d+/(chat_completions|openai_responses)$")
)
async def provider_set_type_handler(client: Client, callback_query: types.CallbackQuery):
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])
    provider_type = parts[3]
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, callback_query.from_user.id):
        await callback_query.answer("You can only edit providers you created.", show_alert=True)
        return
    provider.provider_type = provider_type
    await write_db.merge(provider)
    fresh = await _get_provider(provider_id)
    if fresh:
        await show_provider_edit_menu(
            client, callback_query.message, fresh, callback_query.from_user.id
        )
    await callback_query.answer("Provider type updated.")


@Client.on_callback_query(filters.regex(r"^provider/edit_cancel/\d+$"))
async def provider_edit_cancel_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    provider_id = int(str(callback_query.data).split("/")[2])
    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    provider = await _get_provider(provider_id)
    if provider:
        await show_provider_edit_menu(client, callback_query.message, provider, user_id)
    await callback_query.answer()


# ==================== Text input flow ====================

@Client.on_message(
    filters.create(lambda _, __, m: (
        m.from_user is not None
        and m.from_user.id in _provider_flow
        and not (m.text or "").startswith("/")
    ))  # type: ignore
)
async def provider_flow_conversation_handler(client: Client, message: types.Message):
    user_id = message.from_user.id
    state = _provider_flow.get(user_id)
    if not state:
        return

    text = (message.text or "").strip()
    if not text:
        return True

    try:
        await message.delete()
    except Exception:
        pass

    if state["mode"] == "add":
        step = state["step"]
        if step == "name":
            if len(text) > 50:
                await _safe_edit(
                    client, state["chat_id"], state["menu_msg_id"],
                    "**➕ Add Provider — Name (2/4)**\n\n"
                    "❌ Name must be 50 characters or fewer. Send another name:",
                    _add_nav("provider/add"),
                )
                return True
            existing = await read_db.get_provider_by_name(text)
            if existing:
                await _safe_edit(
                    client, state["chat_id"], state["menu_msg_id"],
                    "**➕ Add Provider — Name (2/4)**\n\n"
                    f"❌ Provider `{text}` already exists. Send a different name:",
                    _add_nav("provider/add"),
                )
                return True
            state["name"] = text
            await _show_add_url(client, state)

        elif step == "url":
            if not text.startswith(("http://", "https://")) or len(text) > 500:
                await _safe_edit(
                    client, state["chat_id"], state["menu_msg_id"],
                    "**➕ Add Provider — Base URL (3/4)**\n\n"
                    "❌ URL must be an `http://` or `https://` URL up to 500 characters.\n\n"
                    "Send a valid base URL:",
                    _add_nav("provider/add_back/name"),
                )
                return True
            state["url"] = text.rstrip("/")
            await _show_add_api_key(client, state)

        elif step == "api_key":
            if len(text) > 500:
                await _safe_edit(
                    client, state["chat_id"], state["menu_msg_id"],
                    "**➕ Add Provider — API Key (4/4)**\n\n"
                    "❌ API key is too long. Send a key up to 500 characters:",
                    _add_nav("provider/add_back/url"),
                )
                return True
            await _finalize_add_provider(client, user_id, state, text)
        return True

    if state["mode"] == "edit":
        provider_id = state["provider_id"]
        provider = await _get_provider(provider_id)
        if not provider or not await _can_manage_provider(provider, user_id):
            _provider_flow.pop(user_id, None)
            flow_state.end_flow(user_id)
            await _safe_edit(
                client, state["chat_id"], state["menu_msg_id"],
                "**⚠️ Provider is unavailable or you no longer have permission to edit it.**",
                types.InlineKeyboardMarkup([[
                    types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/list")
                ]]),
            )
            return True

        step = state["step"]
        if step == "edit_name":
            if len(text) > 50:
                return True
            existing = await read_db.get_provider_by_name(text)
            if existing and existing.id != provider.id:
                await _safe_edit(
                    client, state["chat_id"], state["menu_msg_id"],
                    f"**✏️ Edit Provider — Name**\n\n❌ `{text}` already exists. Send another name:",
                    types.InlineKeyboardMarkup([[
                        types.InlineKeyboardButton(
                            text="⬅️ Back", callback_data=f"provider/edit_cancel/{provider_id}"
                        )
                    ]]),
                )
                return True
            provider.name = text
        elif step == "edit_url":
            if not text.startswith(("http://", "https://")) or len(text) > 500:
                return True
            provider.base_url = text.rstrip("/")
        elif step == "edit_api_key":
            if len(text) > 500:
                return True
            provider.api_key = text

        try:
            await write_db.merge(provider)
        except Exception as exc:
            logger.warning(
                "Failed to update provider %s (%s)", provider_id, type(exc).__name__
            )
            await _safe_edit(
                client, state["chat_id"], state["menu_msg_id"],
                "**❌ Failed to update provider.**\n\nPlease check the values and try again.",
                types.InlineKeyboardMarkup([[
                    types.InlineKeyboardButton(
                        text="⬅️ Back", callback_data=f"provider/edit_cancel/{provider_id}"
                    )
                ]]),
            )
            return True

        _provider_flow.pop(user_id, None)
        flow_state.end_flow(user_id)
        fresh = await _get_provider(provider_id)
        if fresh:
            await show_provider_actions(
                client,
                _EditProxy(client, state["chat_id"], state["menu_msg_id"]),
                fresh,
                user_id,
            )
        return True

    return True


async def _finalize_add_provider(
    client: Client,
    user_id: int,
    state: dict,
    api_key: str,
) -> None:
    provider = AIProvider(
        name=state["name"],
        base_url=state["url"],
        api_key=api_key,
        provider_type=state["provider_type"],
        created_by_user_id=user_id,
    )
    try:
        await write_db.add(provider)
        if await read_db.get_default_provider() is None:
            await write_db.set_default_provider(provider)
    except Exception as exc:
        logger.warning(
            "Failed to add provider %s (%s)", provider.name, type(exc).__name__
        )
        await _safe_edit(
            client, state["chat_id"], state["menu_msg_id"],
            "**❌ Failed to add provider.**\n\nThe name may already exist or the database may be unavailable.",
            types.InlineKeyboardMarkup([[
                types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/list")
            ]]),
        )
        return

    _provider_flow.pop(user_id, None)
    flow_state.end_flow(user_id)
    menu_msg = await client.get_messages(state["chat_id"], state["menu_msg_id"])
    if menu_msg:
        await show_providers_list(client, menu_msg, 0, viewer_user_id=user_id)


# ==================== Provider actions / key ====================

@Client.on_callback_query(filters.regex(r"^provider/\d+$"))
async def provider_number_handler(client: Client, callback_query: types.CallbackQuery):
    provider_num = int(str(callback_query.data).split("/")[1])
    providers = await _all_providers()
    if not 1 <= provider_num <= len(providers):
        await callback_query.answer("Invalid provider number.", show_alert=True)
        return
    await show_provider_actions(
        client,
        callback_query.message,
        providers[provider_num - 1],
        callback_query.from_user.id,
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/key/\d+$"))
async def provider_key_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    user_id = callback_query.from_user.id
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, user_id):
        await callback_query.answer("You cannot view this provider's API key.", show_alert=True)
        return
    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "For safety, API keys can only be revealed in a private chat with the bot.",
            show_alert=True,
        )
        return
    await show_provider_actions(
        client, callback_query.message, provider, user_id, reveal_key=True
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/hide_key/\d+$"))
async def provider_hide_key_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if provider:
        await show_provider_actions(
            client, callback_query.message, provider, callback_query.from_user.id
        )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/select/\d+$"))
async def provider_select_handler(client: Client, callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if not await _is_bot_admin(user_id):
        await callback_query.answer("Only bot admins can change the global default provider.", show_alert=True)
        return
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    await write_db.set_default_provider(provider)
    await show_provider_actions(client, callback_query.message, provider, user_id)
    await callback_query.answer(f"{provider.name} is now the global default provider.")


@Client.on_callback_query(filters.regex(r"^provider/delete/\d+$"))
async def provider_delete_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    user_id = callback_query.from_user.id
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, user_id):
        await callback_query.answer("You can only delete providers you created.", show_alert=True)
        return
    await callback_query.message.edit_text(
        "**🗑️ Delete Provider?**\n\n"
        f"Delete `{provider.name}` permanently?",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(
                text="✅ Yes, Delete", callback_data=f"provider/delete_confirm/{provider_id}"
            )],
            [types.InlineKeyboardButton(
                text="⬅️ Back", callback_data=f"provider/edit_back/{provider_id}"
            )],
        ]),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/delete_confirm/\d+$"))
async def provider_delete_confirm_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    user_id = callback_query.from_user.id
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    if not await _can_manage_provider(provider, user_id):
        await callback_query.answer("You can only delete providers you created.", show_alert=True)
        return
    name = provider.name
    await write_db.delete(provider)
    await show_providers_list(client, callback_query.message, 0, viewer_user_id=user_id)
    await callback_query.answer(f"Deleted {name}.")


# ==================== Models (read only here) ====================

@Client.on_callback_query(filters.regex(r"^provider/models_/\d+$"))
async def provider_models_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    await show_provider_models(
        client, callback_query.message, provider, callback_query.from_user.id, 0
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/models_/\d+/back$"))
async def provider_models_back_compat_handler(client: Client, callback_query: types.CallbackQuery):
    provider_id = int(str(callback_query.data).split("/")[2])
    provider = await _get_provider(provider_id)
    if provider:
        await show_provider_actions(
            client, callback_query.message, provider, callback_query.from_user.id
        )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^provider/models_/\d+/page/\d+$"))
async def provider_models_page_handler(client: Client, callback_query: types.CallbackQuery):
    parts = str(callback_query.data).split("/")
    provider_id = int(parts[2])
    page = int(parts[4])
    provider = await _get_provider(provider_id)
    if not provider:
        await callback_query.answer("Provider not found.", show_alert=True)
        return
    await show_provider_models(
        client, callback_query.message, provider, callback_query.from_user.id, page
    )
    await callback_query.answer()


# ==================== Rendering helpers ====================

async def build_providers_list(
    viewer_user_id: int | None,
    page: int = 0,
    *,
    back_callback: str = "provider/back",
) -> tuple[str, types.InlineKeyboardMarkup]:
    providers = await _all_providers()
    total_pages = max(1, (len(providers) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * ITEMS_PER_PAGE
    page_objects = providers[start_idx:start_idx + ITEMS_PER_PAGE]

    if not providers:
        markup = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton(text="➕ Add Provider", callback_data="provider/add")],
            [types.InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback)],
        ])
        return (
            "**🤖 AI Providers**\n\nNo providers yet.\n\n"
            "Tap **➕ Add Provider** to create one.",
            markup,
        )

    page_list = [(p.id, p.name) for p in page_objects]
    markup = create_providers_keyboard(
        providers=page_list,
        page=page,
        callback_prefix="provider",
        total_pages=total_pages,
        back_callback=back_callback,
    )
    markup.inline_keyboard.insert(0, [
        types.InlineKeyboardButton(text="➕ Add Provider", callback_data="provider/add")
    ])

    lines = []
    for offset, provider in enumerate(page_objects):
        num = start_idx + offset + 1
        mine = viewer_user_id is not None and _is_provider_owner(provider, viewer_user_id)
        marker = " 👤" if mine else ""
        lines.append(
            f"`{num}`. `{provider.name}` — {provider_type_label(provider.provider_type)}{marker}"
        )
    return (
        f"**🤖 AI Providers** (Page {page + 1}/{total_pages})\n\n"
        + "\n".join(lines)
        + "\n\n👤 = provider you created. Tap a number to view details.",
        markup,
    )


async def show_providers_list(
    client: Client,
    message: types.Message,
    page: int = 0,
    force_cloud: bool = False,
    viewer_user_id: int | None = None,
    back_callback: str = "provider/back",
):
    # force_cloud is retained for compatibility with older admin/menu callers.
    del client, force_cloud
    text, markup = await build_providers_list(
        viewer_user_id, page, back_callback=back_callback
    )
    try:
        await message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as exc:
        logger.debug("Could not render provider list: %s", exc)


async def show_provider_actions(
    client: Client,
    message: types.Message,
    provider: AIProvider,
    viewer_user_id: int,
    force_cloud: bool = False,
    reveal_key: bool = False,
):
    del client, force_cloud
    can_manage = await _can_manage_provider(provider, viewer_user_id)
    is_admin = await _is_bot_admin(viewer_user_id)
    default_provider = await read_db.get_default_provider()
    is_default = bool(default_provider and default_provider.id == provider.id)

    if can_manage:
        key_display = provider.api_key if reveal_key else _masked_key(provider.api_key)
    else:
        key_display = "Hidden — owned by another user"

    owner_display = "You" if _is_provider_owner(provider, viewer_user_id) else (
        "Legacy/Admin" if provider.created_by_user_id is None else "Another user"
    )

    buttons: list[list[types.InlineKeyboardButton]] = []
    if is_admin:
        buttons.append([types.InlineKeyboardButton(
            text="⭐ Set Default" if not is_default else "⭐ Global Default",
            callback_data=f"provider/select/{provider.id}" if not is_default else "noop",
        )])
    buttons.append([types.InlineKeyboardButton(
        text="🤖 Models", callback_data=f"provider/models_/{provider.id}"
    )])
    if can_manage:
        buttons.append([
            types.InlineKeyboardButton(
                text="🙈 Hide API Key" if reveal_key else "👁 API Key",
                callback_data=(
                    f"provider/hide_key/{provider.id}" if reveal_key
                    else f"provider/key/{provider.id}"
                ),
            ),
            types.InlineKeyboardButton(text="✏️ Edit", callback_data=f"provider/edit/{provider.id}"),
        ])
        buttons.append([types.InlineKeyboardButton(
            text="🗑️ Delete", callback_data=f"provider/delete/{provider.id}"
        )])
    buttons.append([types.InlineKeyboardButton(text="⬅️ Back", callback_data="provider/list")])

    status = " ⭐ Global Default" if is_default else ""
    await message.edit_text(
        f"**🤖 Provider: {provider.name}**{status}\n\n"
        f"**Type:** `{provider_type_label(provider.provider_type)}`\n"
        f"**URL:** `{provider.base_url}`\n"
        f"**Owner:** {owner_display}\n"
        f"**API Key:** `{key_display}`\n\n"
        "Only the creator can reveal, edit, or delete a user-owned provider.",
        reply_markup=types.InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


async def show_provider_edit_menu(
    client: Client,
    message: types.Message,
    provider: AIProvider,
    viewer_user_id: int,
):
    del client
    if not await _can_manage_provider(provider, viewer_user_id):
        return
    markup = types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="🧩 Type", callback_data=f"provider/edit_type/{provider.id}"
            ),
            types.InlineKeyboardButton(
                text="📝 Name", callback_data=f"provider/edit_field/{provider.id}/name"
            ),
        ],
        [types.InlineKeyboardButton(
            text="🔗 URL", callback_data=f"provider/edit_field/{provider.id}/url"
        )],
        [types.InlineKeyboardButton(
            text="🔑 API Key", callback_data=f"provider/edit_field/{provider.id}/api_key"
        )],
        [types.InlineKeyboardButton(
            text="⬅️ Back", callback_data=f"provider/edit_back/{provider.id}"
        )],
    ])
    await message.edit_text(
        f"**✏️ Edit Provider: {provider.name}**\n\n"
        f"**Type:** `{provider_type_label(provider.provider_type)}`\n"
        f"**URL:** `{provider.base_url}`\n"
        f"**API Key:** `{_masked_key(provider.api_key)}`\n\n"
        "Choose a field to edit.",
        reply_markup=markup,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


async def show_provider_models(
    client: Client,
    message: types.Message,
    provider: AIProvider,
    viewer_user_id: int,
    page: int,
):
    del client
    all_models = await get_provider_models(provider=provider)
    total_pages = max(1, (len(all_models) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE
    page_models = all_models[start:start + ITEMS_PER_PAGE]

    rows: list[list[types.InlineKeyboardButton]] = []
    if page > 0:
        rows.append([types.InlineKeyboardButton(
            text="◀ Prev", callback_data=f"provider/models_/{provider.id}/page/{page - 1}"
        )])
    if page < total_pages - 1:
        rows.append([types.InlineKeyboardButton(
            text="Next ▶", callback_data=f"provider/models_/{provider.id}/page/{page + 1}"
        )])
    rows.append([types.InlineKeyboardButton(
        text="⬅️ Back", callback_data=f"provider/edit_back/{provider.id}"
    )])

    if page_models:
        body = "\n".join(f"`{start + i + 1}`. `{model}`" for i, model in enumerate(page_models))
    else:
        body = "No models available. Check the provider URL/key or configure models manually."

    await message.edit_text(
        f"**🤖 Models for {provider.name}** (Page {page + 1}/{total_pages})\n\n{body}",
        reply_markup=types.InlineKeyboardMarkup(rows),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
