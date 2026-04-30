"""Modelos SQLAlchemy para o MCP."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class McpSession(Base):
    """Sessão de um usuário do MCP — mapeia o bearer token a um canal do YouTube."""

    __tablename__ = "yt_mcp_sessions"

    # Token opaco que o usuário cola no Authorization header
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Identidade do canal
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_handle: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    google_email: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    # OAuth Google — refresh_token criptografado com Fernet
    refresh_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)

    # Quota diária por usuário
    quota_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quota_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Auditoria
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
