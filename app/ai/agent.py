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


# Context management constants
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


def truncate_message(text: str, max_length: int = MESSAGE_TRUNCATE_LENGTH) -> str:
    """Truncate long messages to fit within context"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 50] + "\n...[message truncated]..."


class AIAgent:
    """Improved AIAgent with better context management and error handling"""
    
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

    async def _run_with_mcp_servers(
        self,
        session: SQLiteSession,
        message: types.Message,
        text: str,
        mcp_servers: list,
        functions: list,
    ):
        """Run agent with MCP servers, handling connection lifecycle"""
        if not mcp_servers:
            # No MCP servers, run directly
            res = await Runner.run(
                self.star_chatter(
                    mcp_server=[],
                    message=message,
                    functions=functions,
                ),
                text,
                session=session,
            )
            return res.final_output
        
        # With MCP servers - use context managers
        async with asyncio.timeout(30):
            # Open all MCP servers
            for srv in mcp_servers:
                await srv.__aenter__()
            
            try:
                res = await Runner.run(
                    self.star_chatter(
                        mcp_server=mcp_servers,
                        message=message,
                        functions=functions,
                    ),
                    text,
                    session=session,
                )
                return res.final_output
            finally:
                # Close all MCP servers
                for srv in mcp_servers:
                    await srv.__aexit__(None, None, None)

    async def run_chat(
        self, client: Client, message: types.Message, prompt: str | None = None
    ):
        """
        Process chat request with improved context management and error recovery.
        
        Features:
        - Automatic message truncation to prevent context overflow
        - Retry mechanism with session clearing on context errors
        - Fallback to no-MCP mode on connection failures
        - Detailed logging for debugging group chat issues
        """
        chat_id = message.chat.id
        chat_type = message.chat.type
        
        logger.info(f"Processing chat request from {chat_type} {chat_id}")
        
        # Use session with better context management
        session = SQLiteSession(f"chat_{chat_id}", "conversations.sqlite")

        @function_tool
        def clear_your_memory():
            """Clear conversation history"""
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
                user_id (int): User ID to mute
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
            """Unmute a user in the group"""
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

        # Prepare message text with truncation to prevent context overflow
        text = (
            prompt or truncate_message(message.text or message.caption or "") + f"\n[{message.id}]"
        )

        # Define available functions
        functions = [
            mute_user,
            unmute_user,
            delete_message,
            clear_your_memory,
            list_models,
            set_model,
        ]

        # Retry mechanism with exponential backoff
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
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
                
                # Try to run with MCP servers
                result = await self._run_with_mcp_servers(
                    session=session,
                    message=message,
                    text=text,
                    mcp_servers=mcp_servers,
                    functions=functions,
                )
                
                logger.info(f"Successfully processed chat from {chat_type} {chat_id}")
                return result
                
            except asyncio.TimeoutError as e:
                logger.warning(
                    f"MCP timeout for chat {chat_id} (attempt {attempt + 1}/{max_retries}), "
                    f"falling back to no-MCP mode"
                )
                last_error = e
                
                # Try without MCP servers
                try:
                    result = await Runner.run(
                        self.star_chatter(
                            mcp_server=[],
                            message=message,
                            functions=functions,
                        ),
                        text,
                        session=session,
                    )
                    logger.info(f"Successfully processed chat (no-MCP fallback) from {chat_type} {chat_id}")
                    return result.final_output
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed: {fallback_error}")
                    last_error = fallback_error
                    
            except Exception as e:
                error_msg = str(e).lower()
                last_error = e
                
                # Check if it's a context length error
                is_context_error = any(keyword in error_msg for keyword in [
                    'context length', 'too many tokens', 'maximum context', 
                    'max_tokens', 'context_length_exceeded', 'request too large'
                ])
                
                if is_context_error:
                    logger.warning(
                        f"Context overflow for chat {chat_id} (attempt {attempt + 1}/{max_retries}), "
                        f"clearing session and retrying"
                    )
                    await session.clear_session()
                    
                    # On second retry, also truncate the message more aggressively
                    if attempt == 1:
                        text = truncate_message(text, max_length=500)
                        logger.info(f"Aggressively truncated message for chat {chat_id}")
                else:
                    logger.error(
                        f"Error processing chat from {chat_type} {chat_id} "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
            
            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Waiting {wait_time}s before retry for chat {chat_id}")
                await asyncio.sleep(wait_time)
        
        # All retries failed
        logger.error(
            f"All {max_retries} attempts failed for chat {chat_id}. Last error: {last_error}"
        )
        return (
            "⚠️ Xin lỗi, tôi đang gặp vấn đề kỹ thuật. "
            "Vui lòng thử lại sau hoặc dùng lệnh `/chat` để reset cuộc trò chuyện."
        )
