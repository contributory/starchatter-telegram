from pyrogram import Client, enums, filters, types

from app.ai.base import get_model
from app.ai.base import models as get_models
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.handlers.owner import is_user_owner
from app.handlers.pagination import (
    ITEMS_PER_PAGE,
    create_models_keyboard,
)

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db


@Client.on_callback_query(
    filters.regex(r"models/close")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def models_close_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle close for models list - delete current message only"""
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"models/back")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def models_back_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle back from models list to admin panel"""
    from app.handlers.admin.admin_callbacks import ADMIN_PANEL_TEXT, _build_admin_panel_keyboard
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
    filters.regex(r"models/page/")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def models_page_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle pagination for models list"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")
    page = int(parts[-1])
    await edit_models_list(client, callback_query.message, page)
    await callback_query.answer()


@Client.on_callback_query(
    filters.regex(r"models/\d+")
    & filters.create(lambda _, __, cq: is_user_owner(cq.from_user.id))  # type: ignore
)
async def models_number_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle model selection from list via number button"""
    await callback_query.message.reply_chat_action(enums.ChatAction.TYPING)
    parts = str(callback_query.data).split("/")

    if len(parts) < 2:
        await callback_query.answer("Internal error!", show_alert=True)
        return

    try:
        model_num = int(parts[1])
    except ValueError:
        await callback_query.answer("Internal error!", show_alert=True)
        return

    all_models = await get_models()
    current_model = await get_model()

    # Build models list
    models_list = list(all_models)
    if current_model and current_model in models_list:
        models_list.remove(current_model)
        models_list.insert(0, current_model)
    elif current_model:
        models_list.insert(0, current_model)

    if 1 <= model_num <= len(models_list):
        model_id = models_list[model_num - 1]
        provider = await read_db.get_default_provider()
        if provider:
            await write_db.set_default_model("chat", provider.name, model_id)
            await callback_query.answer(
                f"✅ Selected model: `{model_id}`", show_alert=True
            )
        else:
            await callback_query.answer("⚠️ No provider configured!", show_alert=True)

        # Edit message to show success + back to admin panel
        from app.handlers.admin.admin_callbacks import ADMIN_PANEL_TEXT, _build_admin_panel_keyboard
        try:
            await callback_query.message.edit_text(
                f"✅ **Model Selected**\n\nDefault model set to: `{model_id}`\n\n"
                f"Returning to admin panel...",
                reply_markup=_build_admin_panel_keyboard(),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    else:
        await callback_query.answer("Internal error!", show_alert=True)


async def edit_models_list(client: Client, message: types.Message, page: int = 0):
    """Edit message to show models list with pagination.
    
    Used by both callbacks and navigation from admin panel.
    Uses edit_text instead of sending new messages.
    """
    all_models = await get_models()
    current_model = await get_model()

    # Build models list - current model on top
    models_list = list(all_models)
    if current_model and current_model in models_list:
        models_list.remove(current_model)
        models_list.insert(0, current_model)
    elif current_model:
        models_list.insert(0, current_model)

    if not models_list:
        try:
            await message.edit_text(
                "**⚠️ No Models Available**\n\n"
                "No models found. Check your provider configuration.",
            )
        except Exception:
            pass
        return

    total_pages = max(1, (len(models_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(models_list))
    page_models = models_list[start_idx:end_idx]

    markup = create_models_keyboard(
        models=page_models,
        page=page,
        callback_prefix="models",
        total_pages=total_pages,
        back_callback="models/back",
    )

    # Build message with model names
    start_num = page * ITEMS_PER_PAGE + 1
    model_names = []
    for i, model in enumerate(page_models):
        num = start_num + i
        is_selected = model == current_model
        prefix = "✅ " if is_selected else ""
        model_names.append(f"`{num}`. {prefix}`{model}`")

    models_text = "\n".join(model_names)
    new_text = (
        f"**📋 Models** (Page {page + 1}/{total_pages})\n\n"
        f"{models_text}\n\n"
        f"Tap a number to select model."
    )

    # Skip edit if unchanged
    try:
        if message.text != new_text or str(message.reply_markup) != str(markup):
            await message.edit_text(new_text, reply_markup=markup)
    except Exception:
        pass
