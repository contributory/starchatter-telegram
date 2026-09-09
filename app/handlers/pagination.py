"""Pagination helper functions for AI provider handlers."""

from pyrogram import types

# Paging constants
ITEMS_PER_PAGE = 80  # 10 rows × 8 buttons
COLUMNS = 8  # 8 buttons per row

# Backward compatibility aliases
PROVIDERS_PER_PAGE = ITEMS_PER_PAGE
MODELS_PER_PAGE = ITEMS_PER_PAGE


def create_pagination_buttons(
    page: int, total_pages: int, callback_prefix: str,
    back_callback: str | None = None,
) -> list:
    """Create pagination buttons with always-present Back button.
    
    Args:
        page: Current page number (0-indexed)
        total_pages: Total number of pages
        callback_prefix: Prefix for page callbacks
        back_callback: Callback data for Back button (default: {prefix}/back)
    """
    buttons = []
    row = []

    if page > 0:
        row.append(
            types.InlineKeyboardButton(
                text="◀ Prev", callback_data=f"{callback_prefix}/page/{page - 1}"
            )
        )

    row.append(
        types.InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop",
        )
    )

    if page < total_pages - 1:
        row.append(
            types.InlineKeyboardButton(
                text="Next ▶", callback_data=f"{callback_prefix}/page/{page + 1}"
            )
        )

    # Always include Back button
    back_data = back_callback or f"{callback_prefix}/back"
    row.append(
        types.InlineKeyboardButton(
            text="⬅️ Back",
            callback_data=back_data,
        )
    )

    if row:
        buttons.append(row)

    return buttons


def create_numbered_keyboard(
    items: list[str],
    page: int,
    callback_prefix: str,
    total_pages: int,
    extra_buttons: list[list[types.InlineKeyboardButton]] | None = None,
    back_callback: str | None = None,
) -> types.InlineKeyboardMarkup:
    """Create keyboard displaying list with number buttons and pagination.

    - Each row has 8 number buttons
    - 10 rows for numbers (80 items)
    - Last row for pagination
    """
    buttons: list[list[types.InlineKeyboardButton]] = []
    
    # Calculate starting number for this page
    start_num = page * ITEMS_PER_PAGE + 1
    
    # Number buttons - 8 per row, 10 rows
    for i, item in enumerate(items):
        num = start_num + i
        col = i % COLUMNS
        
        # Start new row every 8 items
        if col == 0:
            buttons.append([])
        
        buttons[-1].append(
            types.InlineKeyboardButton(
                text=str(num),
                callback_data=f"{callback_prefix}/{num}",
            )
        )
    
    # Fill empty slots in last row if needed
    if buttons and len(buttons[-1]) < COLUMNS:
        missing = COLUMNS - len(buttons[-1])
        for _ in range(missing):
            buttons[-1].append(
                types.InlineKeyboardButton(
                    text=" ",
                    callback_data="noop",
                )
            )
    
    # Pagination buttons (last row) - always with Back button
    pagination_buttons = create_pagination_buttons(
        page, total_pages, callback_prefix,
        back_callback=back_callback,
    )
    if pagination_buttons:
        buttons.extend(pagination_buttons)
    
    # Extra buttons
    if extra_buttons:
        buttons.extend(extra_buttons)
    
    return types.InlineKeyboardMarkup(buttons)


def create_models_keyboard(
    models: list[str],
    page: int,
    callback_prefix: str,
    total_pages: int,
    selected_model: str | None = None,
    extra_buttons: list[list[types.InlineKeyboardButton]] | None = None,
    back_callback: str | None = None,
) -> types.InlineKeyboardMarkup:
    """Create keyboard displaying list of models with number buttons and pagination."""
    return create_numbered_keyboard(
        items=models,
        page=page,
        callback_prefix=callback_prefix,
        total_pages=total_pages,
        extra_buttons=extra_buttons,
        back_callback=back_callback,
    )


def create_providers_keyboard(
    providers: list[tuple[int, str]],
    page: int,
    callback_prefix: str,
    total_pages: int,
    extra_buttons: list[list[types.InlineKeyboardButton]] | None = None,
    back_callback: str | None = None,
) -> types.InlineKeyboardMarkup:
    """Create keyboard displaying list of providers with number buttons and pagination.

    Args:
        providers: List of tuples (provider_id, provider_name)
    """
    items = [name for _, name in providers]

    return create_numbered_keyboard(
        items=items,
        page=page,
        callback_prefix=callback_prefix,
        total_pages=total_pages,
        extra_buttons=extra_buttons,
        back_callback=back_callback,
    )
