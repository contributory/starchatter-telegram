import asyncio
from datetime import datetime, timedelta
from app.config import TURSO_AUTH_TOKEN, TURSO_DB_URL
from app.database.local import local_db
from app.database.models import AIProvider, DefaultModel, TelegramUser, Base, MCPServer, ensure_mcp_server_auth_columns
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


class CloudDatabase:
    """LibSQL Cloud database"""

    _instance = None
    _timeout = timedelta(minutes=5)
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
        self._disposed = True
        self._last_used = datetime.now()
        self._closing_task = None
        self._initialized = True

    def _create_engine(self):
        url = TURSO_DB_URL
        if "secure=true" not in url:
            if "?" in url:
                url += "&secure=true"
            else:
                url += "?secure=true"

        self._engine = create_engine(
            url,
            connect_args={"auth_token": TURSO_AUTH_TOKEN} if TURSO_AUTH_TOKEN else {},
        )
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False)
        self._disposed = False

    def init_db(self):
        """Create tables if not exist, run only once on startup."""
        if not self._initialized_db:
            if self._disposed or self._engine is None:
                self._create_engine()
            if self._engine:
                Base.metadata.create_all(self._engine)
                ensure_mcp_server_auth_columns(self._engine)
                self._initialized_db = True

    def _get_session(self) -> Session | None:
        if self._disposed or self._engine is None:
            self._create_engine()
        self._last_used = datetime.now()
        if self._session is None or not self._session.is_active:
            if self._sessionmaker:
                self._session = self._sessionmaker()
        if self._session:
            return self._session

    async def _auto_close(self):
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            if self._session and (now - self._last_used > self._timeout):
                await asyncio.to_thread(self._session.close)
                self._session = None
            if (
                not self._disposed
                and self._engine
                and (now - self._last_used > self._timeout)
            ):
                self._engine.dispose()
                self._disposed = True

    @property
    def engine(self):
        if self._disposed:
            self._create_engine()
        return self._engine

    def _ensure_closing_task(self):
        if self._closing_task is None or self._closing_task.done():
            self._closing_task = asyncio.create_task(self._auto_close())

    async def _run_in_session(self, func, *args, **kwargs):
        self._ensure_closing_task()
        s = self._get_session()
        self._last_used = datetime.now()
        try:
            return await asyncio.to_thread(func, s, *args, **kwargs)
        finally:
            pass

    async def get(self, model, *args, **kwargs):
        result = await self.execute(select(model).filter_by(*args, **kwargs))
        return result.scalars().first()

    async def add(self, obj):
        # Create a copy of the object for cloud database
        cloud_obj = type(obj)(
            **{
                col.name: getattr(obj, col.name)
                for col in obj.__table__.columns
                if hasattr(obj, col.name)
            }
        )
        await self._run_in_session(lambda s, o: s.add(o), cloud_obj)
        await self.commit()  # Commit to cloud database

        # Mirror to local database with a separate object instance
        local_obj = type(obj)(
            **{
                col.name: getattr(obj, col.name)
                for col in obj.__table__.columns
                if hasattr(obj, col.name)
            }
        )
        await local_db.add(local_obj)

    async def add_all(self, objs):
        """Add multiple objects"""
        for obj in objs:
            await self.add(obj)

    async def delete(self, obj):
        # Get the primary key attribute name
        pk_column = obj.__table__.primary_key.columns.values()[0]
        pk_name = pk_column.name
        pk_value = getattr(obj, pk_name)

        # Delete from cloud database
        await self._run_in_session(
            lambda s, pk, model: s.execute(
                model.__table__.delete().where(getattr(model, pk) == pk_value)
            ),
            pk_name,
            type(obj),
        )
        await self.commit()  # Commit to cloud database

        # Delete from local database
        await local_db._run_in_session(
            lambda s, pk, model: s.execute(
                model.__table__.delete().where(getattr(model, pk) == pk_value)
            ),
            pk_name,
            type(obj),
        )
        # Commit to local database
        await local_db.commit()

    async def merge(self, obj):
        # Create a completely new object instance FIRST to avoid session conflicts
        obj_copy = type(obj)(
            **{
                col.name: getattr(obj, col.name)
                for col in obj.__table__.columns
                if hasattr(obj, col.name)
            }
        )
        # Now merge the copy to cloud database (copy is not attached to any session)
        await self._run_in_session(lambda s, o: s.merge(o), obj_copy)
        await self.commit()  # Commit to cloud database

        # Create another copy for local database
        local_obj = type(obj)(
            **{
                col.name: getattr(obj, col.name)
                for col in obj.__table__.columns
                if hasattr(obj, col.name)
            }
        )
        await local_db.merge(local_obj)

    async def commit(self):
        await self._run_in_session(lambda s: s.commit())
        # Mirror commit to local database
        await local_db.commit()

    async def execute(self, *args, **kwargs):
        return await self._run_in_session(lambda s: s.execute(*args, **kwargs))

    # AIProvider methods
    async def get_provider_by_name(self, name: str):
        """Get provider by name"""
        return await self.get(AIProvider, name=name)

    async def get_default_provider(self):
        """Get default provider from DefaultModel"""
        result = await self.execute(
            select(DefaultModel).filter_by(feature="default_provider")
        )
        default_model = result.scalars().first()
        if default_model and default_model.provider_name:
            return await self.get_provider_by_name(default_model.provider_name)
        return None

    async def set_default_provider(self, provider: AIProvider):
        """Set default provider in DefaultModel - mirrors to local"""
        result = await self.execute(
            select(DefaultModel).filter_by(feature="default_provider")
        )
        default_model = result.scalars().first()

        if not default_model:
            default_model = DefaultModel(
                feature="default_provider", provider_name=provider.name
            )
            # Mirror to local database
            await self.add(default_model)
            local_default_model = DefaultModel(
                feature="default_provider", provider_name=provider.name
            )
            await local_db.add(local_default_model)
        else:
            # Update cloud database
            await self._run_in_session(
                lambda s: (
                    s.execute(
                        DefaultModel.__table__.update()
                        .where(DefaultModel.feature == "default_provider")
                        .values(provider_name=provider.name)
                    )
                )
            )
            await self.commit()

            # Mirror update to local database
            await local_db._run_in_session(
                lambda s: (
                    s.execute(
                        DefaultModel.__table__.update()
                        .where(DefaultModel.feature == "default_provider")
                        .values(provider_name=provider.name)
                    )
                )
            )
            await local_db.commit()

    # DefaultModel methods
    async def get_default_model(self, feature: str):
        """Get default model for a feature"""
        result = await self.execute(select(DefaultModel).filter_by(feature=feature))
        return result.scalars().first()

    async def set_default_model(
        self,
        feature: str,
        provider_name: str = None,
        model: str = None,
        config: dict = None,
    ):
        """Set default model for a feature - mirrors to local"""
        result = await self.execute(select(DefaultModel).filter_by(feature=feature))
        default_model = result.scalars().first()

        # Build update data
        update_data = {}
        if provider_name is not None:
            update_data["provider_name"] = provider_name
        if model is not None:
            update_data["model"] = model
        if config is not None:
            update_data["config"] = config

        if not default_model:
            # Create new - will be mirrored by add method
            default_model = DefaultModel(
                feature=feature,
                provider_name=provider_name or "",
                model=model or "",
                config=config or {},
            )
            await self.add(default_model)
        else:
            if update_data:
                # Update cloud database
                await self._run_in_session(
                    lambda s: (
                        s.execute(
                            DefaultModel.__table__.update()
                            .where(DefaultModel.feature == feature)
                            .values(**update_data)
                        )
                    )
                )
                await self.commit()

                # Mirror update to local database
                await local_db._run_in_session(
                    lambda s: (
                        s.execute(
                            DefaultModel.__table__.update()
                            .where(DefaultModel.feature == feature)
                            .values(**update_data)
                        )
                    )
                )
                await local_db.commit()

    # TelegramUser (Owner) methods
    async def get_user(self, user_id: int):
        """Get user by user_id"""
        return await self.get(TelegramUser, id=user_id)

    async def is_owner(self, user_id: int) -> bool:
        """Check if user is owner"""
        user = await self.get_user(user_id)
        return user is not None and user.is_owner if user else False

    async def set_owner(
        self,
        user_id: int,
        is_owner: bool = True,
        username: str = None,
        full_name: str = None,
    ):
        """Set owner privilege for user - mirrors to local"""
        user = await self.get_user(user_id)
        if user:
            # Update cloud user
            update_data = {"is_owner": is_owner}
            if username:
                update_data["username"] = username
            if full_name:
                update_data["first_name"] = full_name

            await self._run_in_session(
                lambda s: (
                    s.execute(
                        TelegramUser.__table__.update()
                        .where(TelegramUser.id == user_id)
                        .values(**update_data)
                    )
                )
            )
            await self.commit()

            # Mirror update to local user
            await local_db._run_in_session(
                lambda s: (
                    s.execute(
                        TelegramUser.__table__.update()
                        .where(TelegramUser.id == user_id)
                        .values(**update_data)
                    )
                )
            )
            await local_db.commit()
        else:
            # Tạo user mới - will be mirrored by add method
            first_name = full_name or ""
            user = TelegramUser(
                id=user_id,
                username=username,
                first_name=first_name,
                is_owner=is_owner,
            )
            await self.add(user)

    async def add_owner(
        self, user_id: int, username: str = None, full_name: str = None
    ):
        """Add new owner"""
        await self.set_owner(user_id, True, username, full_name)

    async def remove_owner(self, user_id: int):
        """Remove owner privilege"""
        await self.set_owner(user_id, False)

    async def get_all_owners(self):
        """Get all owners"""
        result = await self.execute(select(TelegramUser).filter_by(is_owner=True))
        return result.scalars().all()

    # MCPServer methods (mirror writes to local_db)
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

    async def add_mcp_server(
        self, name: str, url: str, description: str = None, enabled: bool = True,
        auth_type: str = "none", auth_config: dict | None = None,
    ):
        """Add or update MCP server - mirrors to local."""
        server = await self.get_mcp_server_by_name(name)
        if server:
            server.url = url
            server.description = description
            server.enabled = enabled
            server.auth_type = auth_type
            server.auth_config = auth_config or {}
            await self.merge(server)
        else:
            server = MCPServer(
                name=name,
                url=url,
                description=description,
                enabled=enabled,
                auth_type=auth_type,
                auth_config=auth_config or {},
            )
            await self.add(server)
        return server

    async def toggle_mcp_server(self, name: str, enabled: bool = None):
        """Toggle MCP server enabled state - mirrors to local"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            if enabled is None:
                server.enabled = not server.enabled
            else:
                server.enabled = enabled
            await self.merge(server)
            return server.enabled
        return None

    async def delete_mcp_server(self, name: str):
        """Delete MCP server - mirrors to local"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            await self.delete(server)
            return True
        return False

    async def update_mcp_server_tools(self, name: str, tools_config: dict):
        """Update tools configuration for MCP server - mirrors to local"""
        server = await self.get_mcp_server_by_name(name)
        if server:
            server.tools_config = tools_config
            await self.merge(server)
            return True
        return False


# Global instance
cloud_db = CloudDatabase()
