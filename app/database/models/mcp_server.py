from sqlalchemy import Boolean, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


def ensure_mcp_server_auth_columns(engine) -> None:
    """Idempotently add MCP auth columns to existing SQLite/libSQL tables."""
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(mcp_servers)")).fetchall()
        }
        if not columns:
            return
        if "auth_type" not in columns:
            connection.execute(
                text("ALTER TABLE mcp_servers ADD COLUMN auth_type VARCHAR(20) DEFAULT 'none'")
            )
        if "auth_config" not in columns:
            connection.execute(text("ALTER TABLE mcp_servers ADD COLUMN auth_config JSON"))


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    auth_config: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    # Store tool-specific enable/disable state
    tools_config: Mapped[dict] = mapped_column(JSON, default=dict)
