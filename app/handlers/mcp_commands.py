"""Command handlers for adding and managing MCP servers."""

from app.handlers.owner import is_user_owner
from pyrogram import Client, enums, filters, types

from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import MCPServer

# Write to cloud (mirrors to local), read from local (faster)
write_db = cloud_db
read_db = local_db


@Client.on_message(
    filters.command("add_mcp")
    & filters.create(lambda _, __, m: is_user_owner(m.from_user.id))  # type: ignore
)
async def add_mcp_handler(client: Client, message: types.Message):
    """Add or update an MCP server
    
    Usage: /add_mcp <name> <url> [description]
    Example: /add_mcp MyTools https://example.com/mcp/sse "My custom tools"
    """
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    args = message.text.split(maxsplit=3)
    
    if len(args) < 4:
        await message.reply(
            "❌ **Usage:** `/add_mcp <name> <url> [description]`\n\n"
            "Example:\n"
            "`/add_mcp MyTools https://example.com/mcp/sse \"My custom tools\"`",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return
    
    name = args[1]
    url = args[2]
    description = args[3] if len(args) > 3 else None
    
    # Validate URL format
    if not url.startswith("http://") and not url.startswith("https://"):
        await message.reply(
            "❌ Invalid URL. Must start with http:// or https://",
            quote=True,
        )
        return
    
    try:
        # Add/update server in database
        server = await write_db.add_mcp_server(name, url, description, enabled=True)
        
        action = "updated" if await read_db.get_mcp_server_by_name(name) else "added"
        
        await message.reply(
            f"✅ MCP server `{name}` has been {action}!\n\n"
            f"**URL:** `{url}`\n"
            f"**Description:** {description or 'None'}\n"
            f"**Status:** ✅ Enabled\n\n"
            f"Use /mcp_servers to view all servers.",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        await message.reply(
            f"❌ Failed to add MCP server: {str(e)}",
            quote=True,
        )


@Client.on_message(
    filters.command("mcp_servers")
    & filters.create(lambda _, __, m: is_user_owner(m.from_user.id))  # type: ignore
)
async def mcp_servers_command_handler(client: Client, message: types.Message):
    """List all MCP servers"""
    from app.handlers.menu_command import mcp_servers_handler
    await mcp_servers_handler(client, message, page=0)


@Client.on_message(
    filters.command("toggle_mcp")
    & filters.create(lambda _, __, m: is_user_owner(m.from_user.id))  # type: ignore
)
async def toggle_mcp_handler(client: Client, message: types.Message):
    """Toggle MCP server enabled state
    
    Usage: /toggle_mcp <name> [on|off]
    Example: /toggle_mcp MyTools off
    """
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    args = message.text.split()
    
    if len(args) < 2:
        await message.reply(
            "❌ **Usage:** `/toggle_mcp <name> [on|off]`\n\n"
            "Examples:\n"
            "`/toggle_mcp MyTools` - Toggle on/off\n"
            "`/toggle_mcp MyTools off` - Disable\n"
            "`/toggle_mcp MyTools on` - Enable",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return
    
    name = args[1]
    state = args[2].lower() if len(args) > 2 else None
    
    if state not in [None, "on", "off"]:
        await message.reply(
            "❌ Invalid state. Use 'on' or 'off'.",
            quote=True,
        )
        return
    
    enabled = None
    if state == "on":
        enabled = True
    elif state == "off":
        enabled = False
    
    result = await write_db.toggle_mcp_server(name, enabled)
    
    if result is None:
        await message.reply(
            f"❌ MCP server `{name}` not found.",
            quote=True,
        )
        return
    
    status = "✅ Enabled" if result else "❌ Disabled"
    await message.reply(
        f"✅ MCP server `{name}` is now {status}.",
        quote=True,
    )


@Client.on_message(
    filters.command("delete_mcp")
    & filters.create(lambda _, __, m: is_user_owner(m.from_user.id))  # type: ignore
)
async def delete_mcp_handler(client: Client, message: types.Message):
    """Delete an MCP server
    
    Usage: /delete_mcp <name>
    Example: /delete_mcp MyTools
    """
    await message.reply_chat_action(enums.ChatAction.TYPING)
    
    args = message.text.split()
    
    if len(args) < 2:
        await message.reply(
            "❌ **Usage:** `/delete_mcp <name>`\n\n"
            "Example:\n"
            "`/delete_mcp MyTools`",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return
    
    name = args[1]
    
    result = await write_db.delete_mcp_server(name)
    
    if result:
        await message.reply(
            f"✅ MCP server `{name}` has been deleted.",
            quote=True,
        )
    else:
        await message.reply(
            f"❌ MCP server `{name}` not found.",
            quote=True,
        )
