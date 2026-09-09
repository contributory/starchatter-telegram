"""Menu command handler with inline keyboard buttons."""

from app.handlers.owner import is_user_owner
from pyrogram import Client, enums, filters, types

from app.database.local import local_db


@Client.on_message(filters.command("menu"))  # type: ignore
async def menu_handler(client: Client, message: types.Message):
    """Show main menu with action buttons"""
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    # Create inline keyboard with menu buttons
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="🤖 Providers",
                callback_data="menu/providers"
            ),
            types.InlineKeyboardButton(
                text="🔧 MCP Servers",
                callback_data="menu/mcp_servers"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⚙️ Models",
                callback_data="menu/models"
            ),
            types.InlineKeyboardButton(
                text="🛠️ Tools",
                callback_data="menu/tools"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="❌ Close",
                callback_data="menu/close"
            ),
        ],
    ]
    
    markup = types.InlineKeyboardMarkup(keyboard)
    
    menu_text = """**📱 Main Menu**

Choose an option:

🤖 **Providers** - Manage AI providers
🔧 **MCP Servers** - Manage MCP servers  
⚙️ **Models** - Configure models
🛠️ **Tools** - Manage tools

Use /help for available commands.
"""
    
    await message.reply(
        menu_text,
        reply_markup=markup,
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@Client.on_callback_query(
    filters.create(lambda _, __, cbq: cbq.data.startswith("menu/"))  # type: ignore
)
async def menu_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle menu button callbacks"""
    from app.handlers.providers_command import providers_handler
    from app.handlers.models_command import models_handler
    
    data = callback_query.data
    action = data.split("/")[1] if "/" in data else ""
    
    # Check if user is owner
    if not is_user_owner(callback_query.from_user.id):
        await callback_query.answer("❌ Only owners can use this menu.", show_alert=True)
        return
    
    if action == "close":
        await callback_query.message.delete()
        return
    
    elif action == "providers":
        await callback_query.answer("Opening providers menu...")
        await callback_query.message.delete()
        # Forward to providers handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/providers",
        )
        await providers_handler(client, fake_message, page=0)
        
    elif action == "mcp_servers":
        await callback_query.answer("Opening MCP servers menu...")
        await callback_query.message.delete()
        # Forward to mcp_servers handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/mcp_servers",
        )
        await mcp_servers_handler(client, fake_message, page=0)
        
    elif action == "models":
        await callback_query.answer("Opening models menu...")
        await callback_query.message.delete()
        # Forward to models handler
        fake_message = types.Message(
            id=callback_query.message.id,
            chat=callback_query.message.chat,
            from_user=callback_query.from_user,
            text="/models",
        )
        await models_handler(client, fake_message, page=0)
        
    elif action == "tools":
        await callback_query.answer("Tools management coming soon!")
        return


async def mcp_servers_handler(client: Client, message: types.Message, page: int = 0):
    """List MCP servers with pagination"""
    from app.handlers.pagination import ITEMS_PER_PAGE, create_providers_keyboard
    
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    servers = await local_db.get_all_mcp_servers()
    
    if not servers:
        await message.reply(
            "No MCP servers configured yet.\n\n"
            "Add an MCP server using:\n"
            "`/add_mcp <name> <url> [description]`",
            quote=True,
        )
        return
    
    # Prepare servers list
    servers_list = [(s.id, s.name, s.enabled) for s in servers]
    
    # Calculate pagination
    total_pages = max(1, (len(servers_list) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(servers_list))
    page_servers = servers_list[start_idx:end_idx]
    
    # Create keyboard
    markup = create_providers_keyboard(
        providers=[(s[0], s[1]) for s in page_servers],
        page=page,
        callback_prefix="mcp",
        total_pages=total_pages,
    )
    
    # Build message
    start_num = page * ITEMS_PER_PAGE + 1
    server_names = []
    for i, (server_id, server_name, enabled) in enumerate(page_servers):
        num = start_num + i
        status = "✅" if enabled else "❌"
        server_names.append(f"`{num}`. {status} `{server_name}`")
    
    servers_text = "\n".join(server_names)
    
    await message.reply(
        f"**🔧 MCP Servers** (Page {page + 1}/{total_pages})\n\n"
        f"{servers_text}\n\n"
        f"Tap a number to manage server.",
        reply_markup=markup,
        quote=True,
    )
