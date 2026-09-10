from sqlalchemy import BigInteger, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


def ensure_ai_provider_columns(engine) -> None:
    """Idempotently add provider ownership/type columns to existing DBs."""
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(ai_providers)")).fetchall()
        }
        if not columns:
            return
        if "provider_type" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE ai_providers ADD COLUMN provider_type "
                    "VARCHAR(40) DEFAULT 'chat_completions'"
                )
            )
        if "created_by_user_id" not in columns:
            connection.execute(
                text("ALTER TABLE ai_providers ADD COLUMN created_by_user_id BIGINT")
            )


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str] = mapped_column(String(500), default="")
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_type: Mapped[str] = mapped_column(String(40), default="chat_completions")
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
