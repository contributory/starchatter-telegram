import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from agents import Agent, Runner, SQLiteSession, function_tool, mcp
from agents.extensions.models.litellm_model import LitellmModel
from pyrogram import Client, types

from app.ai.base import list_models, models, set_model
from app.database.local import local_db

logger = logging.getLogger(__name__)


# Chat history management constants
MAX_MESSAGES_PER_CHAT = 50  # Maximum messages to keep in context
MAX_TOKENS_ESTIMATE = 4000  # Estimated max tokens to avoid context overflow
MESSAGE_TRUNCATE_LENGTH = 1000  # Truncate long messages


async def get_default_provider_and_model():
    """Get default provider and model for chat from local database"""
    default_model = await local_db.get_default_model("chat")
    provider = await local_db.get_default_provider()
    
    model_id = ""
    if default_model and default_model.model:
        model_id = default_model.model

    # Only override provider if default_model has provider_name and provider exists
    if default_model and default_model.provider_name:
        new_provider = await local_db.get_provider_by_name(default_model.provider_name)
        if new_provider:
            provider = new_provider
    
    return provider, model_id


class AIAgent:
    """Simplified AIAgent without complex instance management"""
    
    def __init__(self, provider, model_id):
        """Initialize AIAgent with provider and model"""
        self.model_id = model_id
        self.litellm_model = LitellmModel(
            model="openai/" + model_id,
            base_url=provider.base_url,
            api_key=provider.api_key,
        )

    @classmethod
    async def create(cls):
        """Factory method to create AIAgent"""
        provider, model_id = await get_default_provider_and_model()
        
        # If no model is set, get first model from provider
        if not model_id and provider:
            models_list = await models()
            if models_list:
                model_id = models_list[0]
        
        if provider and model_id:
            return cls(provider, model_id)
        else:
            raise ValueError("No AI provider configured. Use /add_provider to add one.")

    def star_chatter(
        self,
        mcp_server: list,
        message: types.Message,
        functions: list | None = None,
    ):
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
        user_id = (
            message.sender_chat.id if message.sender_chat else message.from_user.id
        )
        return Agent(
            "StarChatter",
            instructions=f"""You are **StarChatter**. You are powered by model `{self.model_id}`. Change model if you can't help the user. To mention a user, use `[user_fullname](tg://user?id=[user_id]).
            - user_fullname: {full_name}
            - user_id: {user_id}
            - message_id: {message.id}
            - previous_message_id: user_message_id - i (i = user_message_id - len(messages_until_target))""",
            tools=functions,
            model=self.litellm_model,
            mcp_servers=mcp_server,
        )

    async def run_chat(
        self, client: Client, message: types.Message, prompt: str | None = None
    ):
        """Process chat request directly without queue management"""
        chat_id = message.chat.id
        
        # Use session with better context management
        session = SQLiteSession(f"chat_{chat_id}", "conversations.sqlite")

        @function_tool
        def clear_your_memory():
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(session.clear_session(), loop)
            return "History cleared."

        @function_tool
        def mute_user(
            user_id: int,
            duration_seconds: int = 0,
        ):
            """
            Mute the user for a specified duration (in seconds).
            If duration less than 30s, mute permanently.

            Args:
                reason (str): Reason for muting the user.
                duration_seconds (int): Duration in seconds to mute the user. Default is 0 (permanent mute).

            Returns:
                str: Success message or error message if muting fails.
            """
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                message.chat.restrict_member(
                    user_id,
                    permissions=types.ChatPermissions(
                        all_perms=False,
                    ),
                    until_date=(datetime.now() + timedelta(seconds=duration_seconds)),
                ),
                loop,
            )
            return "Action completed."

        @function_tool
        def unmute_user(
            group_id: int,
            user_id: int,
        ):
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                client.restrict_chat_member(
                    group_id, user_id, permissions=types.ChatPermissions(all_perms=True)
                ),
                loop,
            )

            return "Action completed."

        @function_tool
        def delete_message(message_ids: int | list[int] | None = None):
            """Delete message with id if provided, otherwise delete the message that triggered the command.

            Args:
                message_ids (int | list[int], optional): Message ID or list of message IDs to delete. Defaults to None and deletes the message that triggered the command.

            Returns:
                str: Success message

            """
            loop = asyncio.get_event_loop()
            if message_ids:
                asyncio.run_coroutine_threadsafe(
                    client.delete_messages(message.chat.id, message_ids), loop
                )
            else:
                asyncio.run_coroutine_threadsafe(message.delete(), loop)
            return "Action completed."

        try:
            # Get enabled MCP servers from database
            enabled_servers = await local_db.get_enabled_mcp_servers()
            mcp_servers = []
            
            # Create MCP server connections for each enabled server
            for server in enabled_servers:
                try:
                    mcp_srv = await mcp.MCPServerSse(
                        name=server.name,
                        params={"url": server.url},
                        cache_tools_list=True,
                    )
                    mcp_servers.append(mcp_srv)
                except Exception as e:
                    logger.warning(f"Failed to connect to MCP server {server.name}: {e}")
            
            # If no MCP servers configured, use empty list
            if not mcp_servers:
                # Still allow chat without MCP
                text = (
                    prompt or (message.text or message.caption or "") + f"\n[{message.id}]"
                )
                res = await Runner.run(
                    self.star_chatter(
                        mcp_server=[],
                        message=message,
                        functions=[
                            mute_user,
                            unmute_user,
                            delete_message,
                            clear_your_memory,
                            list_models,
                            set_model,
                        ],
                    ),
                    text,
                    session=session,
                )
                return res.final_output
            else:
                # Use context manager for MCP servers
                async with asyncio.timeout(30):  # 30 second timeout for MCP connection
                    # Open all MCP servers
                    for srv in mcp_servers:
                        await srv.__aenter__()
                    
                    try:
                        text = (
                            prompt or (message.text or message.caption or "") + f"\n[{message.id}]"
                        )
                        res = await Runner.run(
                            self.star_chatter(
                                mcp_server=mcp_servers,
                                message=message,
                                functions=[
                                    mute_user,
                                    unmute_user,
                                    delete_message,
                                    clear_your_memory,
                                    list_models,
                                    set_model,
                                ],
                            ),
                            text,
                            session=session,
                        )
                        return res.final_output
                    finally:
                        # Close all MCP servers
                        for srv in mcp_servers:
                            await srv.__aexit__(None, None, None)
                            
        except asyncio.TimeoutError:
            logger.warning("MCP server connection timed out, running without MCP tools")
            # Fallback: run without MCP
            text = (
                prompt or (message.text or message.caption or "") + f"\n[{message.id}]"
            )
            res = await Runner.run(
                self.star_chatter(
                    mcp_server=[],
                    message=message,
                    functions=[
                        mute_user,
                        unmute_user,
                        delete_message,
                        clear_your_memory,
                        list_models,
                        set_model,
                    ],
                ),
                text,
                session=session,
            )
            return res.final_output
        except Exception as e:
            logger.error(f"Error processing chat request for chat {chat_id}: {e}")
            raise e
