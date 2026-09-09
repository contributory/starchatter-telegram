import asyncio
import logging
from datetime import datetime, timedelta

from agents import Agent, Runner, SQLiteSession, function_tool, mcp
from agents.extensions.models.litellm_model import LitellmModel
from pyrogram import Client, types

from app.database.local import local_db

logger = logging.getLogger(__name__)

MESSAGE_TRUNCATE_LENGTH = 1000


async def get_default_provider_and_model():
    default_model = await local_db.get_default_model("chat")
    provider = await local_db.get_default_provider()
    model_id = ""
    if default_model and default_model.model:
        model_id = default_model.model
    if default_model and default_model.provider_name:
        new_provider = await local_db.get_provider_by_name(default_model.provider_name)
        if new_provider:
            provider = new_provider
    return provider, model_id


def truncate_message(text: str, max_length: int = MESSAGE_TRUNCATE_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - 50] + "\n...[message truncated]..."


def build_system_tools(client: Client, message: types.Message) -> list:
    """
    Build function_tool list from enabled System Tools in SYSTEM_TOOLS_REGISTRY.
    Only tools with enabled=True are included.
    """
    from app.handlers.system_tools.system_tools_callback import SYSTEM_TOOLS_REGISTRY

    loop = asyncio.get_event_loop()
    chat_id = message.chat.id
    tools = []

    if SYSTEM_TOOLS_REGISTRY.get("telegram.delete_message", {}).get("enabled"):
        @function_tool
        def delete_message(message_ids: int | list[int] | None = None):
            """Delete Telegram message(s).

            Args:
                message_ids: Message ID or list of IDs to delete.
                             If None, deletes the message that triggered this request.
            """
            if message_ids:
                asyncio.run_coroutine_threadsafe(
                    client.delete_messages(chat_id, message_ids), loop
                )
            else:
                asyncio.run_coroutine_threadsafe(message.delete(), loop)
            return "Message(s) deleted."
        tools.append(delete_message)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.edit_message", {}).get("enabled"):
        @function_tool
        def edit_message(message_id: int, text: str):
            """Edit the text of a Telegram message.

            Args:
                message_id: ID of the message to edit.
                text: New text content.
            """
            asyncio.run_coroutine_threadsafe(
                client.edit_message_text(chat_id, message_id, text), loop
            )
            return "Message edited."
        tools.append(edit_message)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.reply_message", {}).get("enabled"):
        @function_tool
        def reply_to_message(message_id: int, text: str):
            """Send a reply to a specific Telegram message.

            Args:
                message_id: ID of the message to reply to.
                text: Reply text.
            """
            asyncio.run_coroutine_threadsafe(
                client.send_message(chat_id, text, reply_to_message_id=message_id), loop
            )
            return "Reply sent."
        tools.append(reply_to_message)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.send_sticker", {}).get("enabled"):
        @function_tool
        def send_sticker(sticker: str):
            """Send a sticker to the current chat.

            Args:
                sticker: Sticker file_id or emoji.
            """
            asyncio.run_coroutine_threadsafe(
                client.send_sticker(chat_id, sticker), loop
            )
            return "Sticker sent."
        tools.append(send_sticker)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.restrict_user", {}).get("enabled"):
        @function_tool
        def restrict_user(user_id: int, duration_seconds: int = 0):
            """Restrict (mute) a user in the group.

            Args:
                user_id: Telegram user ID to restrict.
                duration_seconds: Duration in seconds (0 = permanent).
            """
            asyncio.run_coroutine_threadsafe(
                message.chat.restrict_member(
                    user_id,
                    permissions=types.ChatPermissions(all_perms=False),
                    until_date=(
                        datetime.now() + timedelta(seconds=duration_seconds)
                        if duration_seconds > 0 else None
                    ),
                ),
                loop,
            )
            return "User restricted."
        tools.append(restrict_user)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.kick_user", {}).get("enabled"):
        @function_tool
        def kick_user(user_id: int):
            """Remove (kick) a user from the group.

            Args:
                user_id: Telegram user ID to kick.
            """
            asyncio.run_coroutine_threadsafe(
                client.ban_chat_member(chat_id, user_id), loop
            )
            return "User kicked."
        tools.append(kick_user)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.unban_user", {}).get("enabled"):
        @function_tool
        def unban_user(user_id: int):
            """Unban a user in the chat.

            Args:
                user_id: Telegram user ID to unban.
            """
            asyncio.run_coroutine_threadsafe(
                client.unban_chat_member(chat_id, user_id), loop
            )
            return "User unbanned."
        tools.append(unban_user)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.edit_group_description", {}).get("enabled"):
        @function_tool
        def edit_group_description(description: str):
            """Edit the group description.

            Args:
                description: New group description text.
            """
            asyncio.run_coroutine_threadsafe(
                client.set_chat_description(chat_id, description), loop
            )
            return "Group description updated."
        tools.append(edit_group_description)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.edit_channel_description", {}).get("enabled"):
        @function_tool
        def edit_channel_description(description: str):
            """Edit the channel description.

            Args:
                description: New channel description text.
            """
            asyncio.run_coroutine_threadsafe(
                client.set_chat_description(chat_id, description), loop
            )
            return "Channel description updated."
        tools.append(edit_channel_description)

    if SYSTEM_TOOLS_REGISTRY.get("telegram.post_to_channel", {}).get("enabled"):
        @function_tool
        def post_to_channel(channel_id: int, text: str):
            """Post a message to a channel.

            Args:
                channel_id: Target channel ID.
                text: Message text to post.
            """
            asyncio.run_coroutine_threadsafe(
                client.send_message(channel_id, text), loop
            )
            return "Posted to channel."
        tools.append(post_to_channel)

    return tools


class AIAgent:
    """AIAgent powered by enabled System Tools from registry."""

    def __init__(self, provider, model_id):
        self.model_id = model_id
        self.litellm_model = LitellmModel(
            model="openai/" + model_id,
            base_url=provider.base_url,
            api_key=provider.api_key,
        )

    @classmethod
    async def create(cls):
        from app.ai.base import models
        provider, model_id = await get_default_provider_and_model()
        if not model_id and provider:
            models_list = await models()
            if models_list:
                model_id = models_list[0]
        if provider and model_id:
            return cls(provider, model_id)
        raise ValueError("No AI provider configured. Use /add_provider to add one.")

    def star_chatter(self, mcp_server: list, message: types.Message, functions: list | None = None):
        if functions is None:
            functions = []
        full_name = (
            (
                f"{message.sender_chat.title} (Group/Anonymous Admin)"
                if message.sender_chat.title == message.chat.title
                else f"{message.sender_chat.title} (Channel/Anonymous User)"
            )
            if message.sender_chat
            else message.from_user.full_name
        )
        user_id = message.sender_chat.id if message.sender_chat else message.from_user.id
        return Agent(
            "StarChatter",
            instructions=(
                f"You are **StarChatter**, a helpful Telegram AI assistant. "
                f"You are powered by model `{self.model_id}`.\n"
                f"- User: {full_name} (ID: {user_id})\n"
                f"- Message ID: {message.id}\n"
                f"- To mention user: `[{full_name}](tg://user?id={user_id})`\n\n"
                f"Use the available tools to help users. "
                f"Only use destructive tools (delete, kick, restrict) when clearly requested."
            ),
            tools=functions,
            model=self.litellm_model,
            mcp_servers=mcp_server,
        )

    async def _run_with_mcp_servers(
        self,
        session: SQLiteSession,
        message: types.Message,
        text: str,
        mcp_servers: list,
        functions: list,
    ):
        if not mcp_servers:
            res = await Runner.run(
                self.star_chatter(mcp_server=[], message=message, functions=functions),
                text,
                session=session,
            )
            return res.final_output

        async with asyncio.timeout(30):
            for srv in mcp_servers:
                await srv.__aenter__()
            try:
                res = await Runner.run(
                    self.star_chatter(mcp_server=mcp_servers, message=message, functions=functions),
                    text,
                    session=session,
                )
                return res.final_output
            finally:
                for srv in mcp_servers:
                    await srv.__aexit__(None, None, None)

    async def run_chat(self, client: Client, message: types.Message, prompt: str | None = None):
        """
        Process chat request with System Tools integration.
        Returns None on failure so chatbot_listener can show error with buttons.
        """
        chat_id = message.chat.id
        chat_type = message.chat.type
        logger.info(f"Processing chat from {chat_type} {chat_id}")

        session = SQLiteSession(f"chat_{chat_id}", "conversations.sqlite")
        functions = build_system_tools(client, message)
        logger.info(f"Loaded {len(functions)} system tools for chat {chat_id}")

        text = (
            prompt
            or truncate_message(message.text or message.caption or "")
            + f"\n[{message.id}]"
        )

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                enabled_servers = await local_db.get_enabled_mcp_servers()
                mcp_servers = []
                for server in enabled_servers:
                    try:
                        mcp_srv = await mcp.MCPServerSse(
                            name=server.name,
                            params={"url": server.url},
                            cache_tools_list=True,
                        )
                        mcp_servers.append(mcp_srv)
                    except Exception as e:
                        logger.warning(f"Failed to connect MCP server {server.name}: {e}")

                result = await self._run_with_mcp_servers(
                    session=session,
                    message=message,
                    text=text,
                    mcp_servers=mcp_servers,
                    functions=functions,
                )
                logger.info(f"Success chat {chat_id}")
                return result

            except asyncio.TimeoutError as e:
                logger.warning(f"MCP timeout chat {chat_id} attempt {attempt+1}, fallback no-MCP")
                last_error = e
                try:
                    result = await Runner.run(
                        self.star_chatter(mcp_server=[], message=message, functions=functions),
                        text,
                        session=session,
                    )
                    return result.final_output
                except Exception as fe:
                    logger.error(f"Fallback failed: {fe}")
                    last_error = fe

            except Exception as e:
                error_msg = str(e).lower()
                last_error = e
                is_context_error = any(k in error_msg for k in [
                    "context length", "too many tokens", "maximum context",
                    "max_tokens", "context_length_exceeded", "request too large",
                ])
                if is_context_error:
                    logger.warning(f"Context overflow chat {chat_id} attempt {attempt+1}, clearing")
                    await session.clear_session()
                    if attempt == 1:
                        text = truncate_message(text, max_length=500)
                else:
                    logger.error(f"Error chat {chat_id} attempt {attempt+1}: {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        logger.error(f"All {max_retries} attempts failed chat {chat_id}: {last_error}")
        return None  # chatbot_listener will show error with action buttons
