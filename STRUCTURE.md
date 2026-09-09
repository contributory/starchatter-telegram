# Starchatter Handler Structure

## Directory Layout

```
app/handlers/
├── admin/                      # Admin panel handlers
│   ├── __init__.py
│   ├── super_command.py        # /super command - Admin panel main menu
│   └── admin_callbacks.py      # Admin panel navigation callbacks
│
├── chat/                       # Chat menu handlers
│   ├── __init__.py
│   └── chat_menu.py            # /chat command and callbacks
│
├── system_tools/               # Telegram System Tools
│   ├── __init__.py
│   └── system_tools_callback.py # System tools registry and handlers
│
├── mcp_callbacks.py            # MCP server management (admin:mcp:*)
├── mcp_commands.py             # MCP commands (/add_mcp, /mcp_servers, etc.)
├── menu_command.py             # /menu command with inline buttons
├── providers_command.py        # /providers command
├── provider_callbacks.py       # Provider management callbacks
├── models_command.py           # /models command
├── models_callbacks.py         # Model selection callbacks
├── setmodel_command.py         # /setmodel command
├── setmodel_callback.py        # Model configuration callbacks
├── pagination.py               # Pagination utilities
├── owner.py                    # Owner permission checks
└── noop_callback.py            # No-op callback handler
```

## Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/super` | Administrator Panel | Owner only |
| `/chat` | Chat Menu | All users |
| `/menu` | Main Menu | All users |
| `/providers` | AI Providers List | All users |
| `/models` | Models List | All users |
| `/add_mcp` | Add MCP Server | Owner only |
| `/mcp_servers` | List MCP Servers | All users |
| `/toggle_mcp` | Toggle MCP Server | Owner only |
| `/delete_mcp` | Delete MCP Server | Owner only |

## Callback Conventions

### Admin Panel Callbacks
- `admin:providers` - Open providers menu
- `admin:models` - Open models menu
- `admin:mcp_servers` - Open MCP servers menu
- `admin:system_tools` - Open system tools menu
- `admin:chat_settings` - Open chat settings
- `admin:bot_settings` - Open bot settings
- `admin:back` - Return to admin panel

### MCP Callbacks
- `admin:mcp/page/{page}` - MCP pagination
- `admin:mcp/back` - Back to MCP list
- `admin:mcp/close` - Close MCP menu
- `admin:mcp/{number}` - Select MCP server by number
- `admin:mcp/toggle/{server_name}` - Toggle MCP server
- `admin:mcp/delete/{server_name}` - Delete MCP server
- `admin:mcp/tools/{server_name}` - View MCP tools
- `admin:mcp/actions/{server_name}` - Back to server actions

### System Tools Callbacks
- `admin:system_tool:view:{tool_id}` - View tool details
- `admin:system_tool:toggle:{tool_id}` - Toggle tool enabled state

### Chat Callbacks
- `chat:reset` - Reset chat (show confirmation)
- `chat:reset:confirm` - Confirm reset
- `chat:save` - Save conversation
- `chat:save:markdown` - Save as markdown
- `chat:conversations` - List conversations
- `chat:toggle` - Enable/disable chat
- `chat:menu` - Return to chat menu

## System Tools Registry

Fixed set of 10 Telegram native capabilities:

### Message Tools
- `telegram.delete_message` - Delete messages
- `telegram.edit_message` - Edit messages
- `telegram.reply_message` - Reply to messages
- `telegram.send_sticker` - Send stickers

### User Moderation Tools
- `telegram.restrict_user` - Mute/restrict users
- `telegram.kick_user` - Kick users (destructive)
- `telegram.unban_user` - Unban users

### Group/Channel Management
- `telegram.edit_group_description` - Edit group description
- `telegram.edit_channel_description` - Edit channel description
- `telegram.post_to_channel` - Post to channels

## API Key Security

API Keys are ONLY handled in:
- Private chats between bot and owner
- Never in groups/supergroups/channels
- Never in callback_data
- Never in logs or AI context

## Navigation Flow

```
/super → Admin Panel
├── Providers → Provider List → Provider Detail
├── List Models → Model List → Model Detail
├── MCP Servers → MCP List → Server Detail
├── System Tools → Tool List → Tool Detail
├── Chat Settings (coming soon)
├── Bot Settings (coming soon)
└── Web Panel (URL button)

/chat → Chat Menu
├── Reset Chat → Confirmation
├── Save Conversation → Format Selection
├── Conversations → Conversation List
└── Enable/Disable

/menu → Main Menu
├── Providers
├── MCP Servers
├── Models
└── Tools
```
