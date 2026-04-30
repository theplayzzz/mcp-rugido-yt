"""Tracking de quota da YouTube Data API por sessão MCP.

Padrão de uso:
- O middleware Bearer carrega o quota_used do DB pra dentro de um RequestQuota
  e popula o ContextVar antes da tool rodar.
- Cada tool chama `quota.consume("list")` — síncrono, atualiza só o estado
  in-memory.
- No fim da request, o middleware persiste o novo quota_used no DB.

Esse padrão evita I/O assíncrono no meio das tools (que são sync) e mantém
um único UPDATE por request mesmo com múltiplas chamadas internas à API.
"""

from contextvars import ContextVar
from datetime import datetime, timezone

from mcp_rugido_yt.config import get_settings


class QuotaExhaustedError(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
        super().__init__(
            f"Quota da YouTube API esgotada para essa sessão: "
            f"{used}/{limit} unidades usadas hoje."
        )


# Custos por operação (Google docs)
QUOTA_COSTS = {
    "list": 1,
    "insert": 50,
    "update": 50,
    "delete": 50,
    "search": 100,
    "video_insert": 1600,
    "caption_insert": 400,
    "caption_update": 450,
    "thumbnail_set": 50,
}


class RequestQuota:
    """Estado de quota carregado pra atender uma request MCP."""

    def __init__(
        self,
        session_id: str,
        used: int,
        reset_at: datetime,
        daily_limit: int | None = None,
    ):
        self.session_id = session_id
        self.reset_at = reset_at
        self.daily_limit = daily_limit or get_settings().daily_quota_limit
        self._initial_used = used
        self._used = used
        self._reset_if_due()

    def _reset_if_due(self) -> None:
        if datetime.now(timezone.utc) >= self.reset_at:
            self._used = 0
            self._initial_used = 0

    def consume(self, operation: str, count: int = 1) -> None:
        cost = QUOTA_COSTS.get(operation, 1) * count
        if self._used + cost > self.daily_limit:
            raise QuotaExhaustedError(self._used, self.daily_limit)
        self._used += cost

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self.daily_limit - self._used

    @property
    def dirty(self) -> bool:
        return self._used != self._initial_used

    def status(self) -> dict:
        return {
            "used": self._used,
            "remaining": self.remaining,
            "limit": self.daily_limit,
            "reset_at": self.reset_at.isoformat(),
        }


_current_quota: ContextVar[RequestQuota | None] = ContextVar(
    "current_quota", default=None
)


def set_current_quota(quota: RequestQuota | None) -> None:
    _current_quota.set(quota)


def get_current_quota() -> RequestQuota:
    q = _current_quota.get()
    if q is None:
        raise RuntimeError(
            "Sem RequestQuota no contexto — middleware Bearer não rodou? "
            "Tools só funcionam dentro de uma request MCP autenticada."
        )
    return q


class _QuotaProxy:
    """Fachada global que delega pro RequestQuota da request atual.

    Permite que as tools façam `quota.consume("list")` sem precisar passar
    estado por argumento.
    """

    def consume(self, operation: str, count: int = 1) -> None:
        get_current_quota().consume(operation, count)

    @property
    def used(self) -> int:
        return get_current_quota().used

    @property
    def remaining(self) -> int:
        return get_current_quota().remaining

    def status(self) -> dict:
        try:
            return get_current_quota().status()
        except RuntimeError:
            return {"error": "Sem sessão ativa"}


quota = _QuotaProxy()
