"""ContextVars de request + proxies usados pelas tools.

As tools são sync e foram escritas pra usar `auth` e `quota` como singletons.
Pra preservar essa interface no novo modelo multi-tenant, usamos ContextVars
populadas pelo middleware Bearer antes de cada chamada de tool.
"""

from contextvars import ContextVar

from mcp_rugido_yt.auth import YouTubeAuth
from mcp_rugido_yt.sessions import SessionData

_current_session: ContextVar[SessionData | None] = ContextVar(
    "current_session", default=None
)


def set_current_session(session: SessionData | None) -> None:
    _current_session.set(session)


def get_current_session() -> SessionData:
    s = _current_session.get()
    if s is None:
        raise RuntimeError(
            "Sem sessão ativa — tools só funcionam dentro de uma request MCP autenticada."
        )
    return s


class _AuthProxy:
    """Fachada global que constrói YouTubeAuth pra sessão atual sob demanda."""

    def _instance(self) -> YouTubeAuth:
        return YouTubeAuth(get_current_session())

    def build_youtube_service(self):
        return self._instance().build_youtube_service()

    def build_youtube_analytics_service(self):
        return self._instance().build_youtube_analytics_service()

    def build_youtube_reporting_service(self):
        return self._instance().build_youtube_reporting_service()

    def build_public_youtube_service(self):
        return self._instance().build_public_youtube_service()

    def status(self) -> dict:
        try:
            s = get_current_session()
        except RuntimeError:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "channel_id": s.channel_id,
            "channel_handle": s.channel_handle,
            "channel_title": s.channel_title,
            "google_email": s.google_email,
            "scopes": s.scope.split(),
        }


auth = _AuthProxy()
