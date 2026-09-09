from sqlalchemy import String, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    # Store tool-specific enable/disable state
    tools_config: Mapped[dict] = mapped_column(JSON, default=dict)
