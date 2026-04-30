"""Repositório de sessões MCP — CRUD sobre yt_mcp_sessions."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_rugido_yt.crypto import decrypt, encrypt
from mcp_rugido_yt.db.models import McpSession

SESSION_PREFIX = "ymp_"


def generate_session_id() -> str:
    """Gera um session_id opaco (formato ymp_<43 chars>)."""
    return SESSION_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class SessionData:
    """Snapshot imutável de uma sessão, seguro para usar fora da transação."""

    session_id: str
    channel_id: str
    channel_handle: str | None
    channel_title: str | None
    google_email: str
    refresh_token: str  # já decriptado
    scope: str
    quota_used: int
    quota_reset_at: datetime


async def create_session(
    db: AsyncSession,
    *,
    channel_id: str,
    channel_handle: str | None,
    channel_title: str | None,
    google_email: str,
    refresh_token: str,
    scope: str,
) -> str:
    """Cria sessão. Se já existe sessão para esse channel_id, revoga e cria nova."""
    # Revoga sessões prévias do mesmo canal (1 sessão ativa por canal)
    await db.execute(
        update(McpSession)
        .where(
            McpSession.channel_id == channel_id,
            McpSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )

    session_id = generate_session_id()
    row = McpSession(
        session_id=session_id,
        channel_id=channel_id,
        channel_handle=channel_handle,
        channel_title=channel_title,
        google_email=google_email,
        refresh_token_enc=encrypt(refresh_token),
        scope=scope,
        quota_used=0,
        quota_reset_at=_next_quota_reset(),
    )
    db.add(row)
    await db.commit()
    return session_id


async def get_session_data(db: AsyncSession, session_id: str) -> SessionData | None:
    """Busca sessão ativa pelo session_id. Retorna None se não existe ou foi revogada."""
    if not session_id.startswith(SESSION_PREFIX):
        return None
    row = await db.get(McpSession, session_id)
    if row is None or row.revoked_at is not None:
        return None
    return SessionData(
        session_id=row.session_id,
        channel_id=row.channel_id,
        channel_handle=row.channel_handle,
        channel_title=row.channel_title,
        google_email=row.google_email,
        refresh_token=decrypt(row.refresh_token_enc),
        scope=row.scope,
        quota_used=row.quota_used,
        quota_reset_at=row.quota_reset_at,
    )


async def touch_session(db: AsyncSession, session_id: str) -> None:
    """Atualiza last_used_at."""
    await db.execute(
        update(McpSession)
        .where(McpSession.session_id == session_id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def revoke_session(db: AsyncSession, session_id: str) -> bool:
    """Revoga sessão. Retorna True se algo foi revogado."""
    result = await db.execute(
        update(McpSession)
        .where(
            McpSession.session_id == session_id,
            McpSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return result.rowcount > 0


async def list_sessions_by_email(db: AsyncSession, email: str) -> list[McpSession]:
    """Útil pra UI de gestão (lista canais conectados por um email)."""
    result = await db.execute(
        select(McpSession)
        .where(McpSession.google_email == email, McpSession.revoked_at.is_(None))
        .order_by(McpSession.created_at.desc())
    )
    return list(result.scalars())


def _next_quota_reset() -> datetime:
    """Próxima virada de dia em UTC. (YouTube reseta em Pacific Time, mas pra MVP UTC já basta.)"""
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
