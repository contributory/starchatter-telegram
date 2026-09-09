import asyncio
from datetime import datetime, timedelta


from app.database.models import AIProvider, DefaultModel, TelegramUser, TelegramGroup, TelegramChannel, GroupMember, ChannelMember, Base, MCPServer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

LIBSQL_DB_URL = "sqlite:///local.db"


class LocalDatabase:
    """
    Local database - always open, no auto-close
    """

    _instance = None
    _initialized_db = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._engine = None
        self._sessionmaker = None
        self._session = None
        self._initialized = True

    def _create_engine(self):
        self._engine = create_engine(
            LIBSQL_DB_URL,
        )
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False)

    def init_db(self):
        """Create tables if not exist, run only once on startup."""
        if not self._initialized_db:
            if self._engine is None:
                self._create_engine()
            if self._engine:
                Base.metadata.create_all(self._engine)
                self._initialized_db = True

    def _get_session(self) -> Session | None:
        if self._engine is None:
            self._create_engine()
        if self._session is None or not self._session.is_active:
            if self._sessionmaker:
                self._session = self._sessionmaker()
        if self._session:
            return self._session

    @property
    def engine(self):
        if self._engine is None:
            self._create_engine()
        return self._engine

    async def _run_in_session(self, func, *args, **kwargs):
        s = self._get_session()
        try:
            return await asyncio.to_thread(func, s, *args, **kwargs)
        finally:
            pass

    async def get(self, model, *args, **kwargs):
        result = await self.execute(select(model).filter_by(*args, **kwargs))
        return result.scalars().first()

    async def add(self, obj):
        await self._run_in_session(lambda s, o: (s.add(o), s.commit()), obj)

    async def delete(self, obj):
        await self._run_in_session(lambda s, o: (s.delete(o), s.commit()), obj)

    async def merge(self, obj):
        await self._run_in_session(lambda s, o: (s.merge(o), s.commit()), obj)

    async def commit(self):
        await self._run_in_session(lambda s: s.commit())

    async def execute(self, *args, **kwargs):
        return await self._run_in_session(lambda s: s.execute(*args, **kwargs))

    # AIProvider methods
    async def get_provider_by_name(self, name: str):
        """Get provider by name"""
        return await self.get(AIProvider, name=name)

    async def get_default_provider(self):
        """Get default provider from DefaultModel"""
        result = await self.execute(select(DefaultModel).filter_by(feature="default_provider"))
        default_model = result.scalars().first()
        if default_model and default_model.provider_name:
            return await self.get_provider_by_name(default_model.provider_name)
        return None

    async def set_default_provider(self, provider: AIProvider):
        """Set default provider in DefaultModel"""
        result = await self.execute(select(DefaultModel).filter_by(feature="default_provider"))
        default_model = result.scalars().first()
        
        if not default_model:
            default_model = DefaultModel(feature="default_provider", provider_name=provider.name)
            await self.add(default_model)
        else:
            default_model.provider_name = provider.name
            await self.commit()

    # DefaultModel methods
    async def get_default_model(self, feature: str):
        """Get default model for a feature"""
        result = await self.execute(select(DefaultModel).filter_by(feature=feature))
        return result.scalars().first()

    async def set_default_model(self, feature: str, provider_name: str = None, model: str = None, config: dict = None):
        """Set default model for a feature"""
        result = await self.execute(select(DefaultModel).filter_by(feature=feature))
        default_model = result.scalars().first()
        
        if not default_model:
            default_model = DefaultModel(
                feature=feature,
                provider_name=provider_name,
                model=model,
                config=config or {}
            )
            await self.add(default_model)
        else:
            if provider_name is not None:
                default_model.provider_name = provider_name
            if model is not None:
                default_model.model = model
            if config is not None:
                default_model.config = config
            await self.commit()

    # TelegramUser (Owner) methods
    async def get_user(self, user_id: int):
        """Get user by user_id"""
        return await self.get(TelegramUser, id=user_id)

    async def is_owner(self, user_id: int) -> bool:
        """Check if user is owner"""
        user = await self.get_user(user_id)
        return user is not None and user.is_owner if user else False

    async def set_owner(self, user_id: int, is_owner: bool = True, username: str = None, full_name: str = None):
        """Set owner privilege for user"""
        user = await self.get_user(user_id)
        if user:
            user.is_owner = is_owner
            if username:
                user.username = username
            if full_name:
                user.first_name = full_name
            await self.commit()
        else:
            # Tạo user mới
            first_name = full_name or ""
            user = TelegramUser(
                id=user_id,
                username=username,
                first_name=first_name,
                is_owner=is_owner,
            )
            await self.add(user)

    async def add_owner(self, user_id: int, username: str = None, full_name: str = None):
        """Add new owner"""
        await self.set_owner(user_id, True, username, full_name)

    async def remove_owner(self, user_id: int):
        """Remove owner privilege"""
        await self.set_owner(user_id, False)

    async def get_all_owners(self):
        """Get all owners"""
        result = await self.execute(select(TelegramUser).filter_by(is_owner=True))
        return result.scalars().all()

    # TelegramGroup methods
    async def get_group(self, group_id: int):
        """Get group by group_id"""
        return await self.get(TelegramGroup, id=group_id)

    async def add_group(self, group_id: int, title: str, username: str = None):
        """Add or update group"""
        group = await self.get_group(group_id)
        if group:
            group.title = title
            if username:
                group.username = username
            await self.commit()
        else:
            group = TelegramGroup(
                id=group_id,
                title=title,
                username=username,
            )
            await self.add(group)

    async def get_channel(self, channel_id: int):
        """Get channel by channel_id"""
        return await self.get(TelegramChannel, id=channel_id)

    async def add_channel(self, channel_id: int, title: str, username: str = None):
        """Add or update channel"""
        channel = await self.get_channel(channel_id)
        if channel:
            channel.title = title
            if username:
                channel.username = username
            await self.commit()
        else:
            channel = TelegramChannel(
                id=channel_id,
                title=title,
                username=username,
            )
            await self.add(channel)

    async def add_or_update_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Add or update user"""
        user = await self.get_user(user_id)
        if user:
            if username:
                user.username = username
            if first_name:
                user.first_name = first_name
            if last_name:
                user.last_name = last_name
            await self.commit()
        else:
            user = TelegramUser(
                id=user_id,
                username=username,
                first_name=first_name or "",
                last_name=last_name,
            )
            await self.add(user)
        return user

    async def add_group_member(self, user_id: int, group_id: int, is_admin: bool = False, is_owner: bool = False):
        """Add member to group with admin status"""
        # Ensure user and group exist
        user = await self.add_or_update_user(user_id)
        await self.add_group(group_id, "")

        # Check and add/update member
        result = await self.execute(
            select(GroupMember).filter_by(user_id=user_id, group_id=group_id)
        )
        member = result.scalars().first()
        
        if member:
            member.is_admin = is_admin
            member.is_owner = is_owner
            await self.commit()
        else:
            member = GroupMember(
                user_id=user_id,
                group_id=group_id,
                is_admin=is_admin,
                is_owner=is_owner,
            )
            await self.add(member)

    async def add_channel_member(self, user_id: int, channel_id: int, is_admin: bool = False, is_owner: bool = False):
        """Add member to channel with admin status"""
        # Ensure user and channel exist
        user = await self.add_or_update_user(user_id)
        await self.add_channel(channel_id, "")

        # Check and add/update member
        result = await self.execute(
            select(ChannelMember).filter_by(user_id=user_id, channel_id=channel_id)
        )
        member = result.scalars().first()
        
        if member:
            member.is_admin = is_admin
            member.is_owner = is_owner
            await self.commit()
        else:
            member = ChannelMember(
                user_id=user_id,
                channel_id=channel_id,
                is_admin=is_admin,
                is_owner=is_owner,
            )
            await self.add(member)

    # MCPServer methods
    async def get_mcp_server_by_name(self, name: str):
        """Get MCP server by name"""
        return await self.get(MCPServer, name=name)

    async def get_all_mcp_servers(self):
        """Get all MCP servers"""
        result = await self.execute(select(MCPServer))
        return result.scalars().all()

    async def get_enabled_mcp_servers(self):
        """Get all enabled MCP servers"""
        result = await self.execute(select(MCPServer).filter_by(enabled=True))
        return result.scalars().all()

    async def add_mcp_server(self, name: str, url: str, description: str = None, enabled: bool = True):
        """Add or update MCP server"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            server.url = url
            if description:
                server.description = description
            server.enabled = enabled
            await self.commit()
        else:
            server = MCPServer(
                name=name,
                url=url,
                description=description,
                enabled=enabled,
            )
            await self.add(server)
        return server

    async def toggle_mcp_server(self, name: str, enabled: bool = None):
        """Toggle MCP server enabled state"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            if enabled is None:
                server.enabled = not server.enabled
            else:
                server.enabled = enabled
            await self.commit()
            return server.enabled
        return None

    async def delete_mcp_server(self, name: str):
        """Delete MCP server"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            await self.delete(server)
            return True
        return False

    async def update_mcp_server_tools(self, name: str, tools_config: dict):
        """Update tools configuration for MCP server"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            server.tools_config = tools_config
            await self.commit()
            return True
        return False


# Global instance
local_db = LocalDatabase()
