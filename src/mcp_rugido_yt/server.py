"""MCP Rugido YT — entrypoint do servidor multi-tenant.

Expõe:
- /mcp                — endpoint MCP (streamable-http) com Bearer auth
- /oauth/connect      — inicia o fluxo OAuth do Google
- /oauth/callback     — recebe o code do Google e mostra o session_id pro user
- /health             — healthcheck pro Dokploy/Traefik
"""

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape

from mcp.server.fastmcp import FastMCP
from sqlalchemy import update
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp_rugido_yt.auth import build_authorization_url, exchange_code
from mcp_rugido_yt.config import get_settings
from mcp_rugido_yt.db import init_engine, session_factory, shutdown_engine
from mcp_rugido_yt.db.models import McpSession
from mcp_rugido_yt.runtime import auth, set_current_session
from mcp_rugido_yt.sessions import create_session, get_session_data, touch_session
from mcp_rugido_yt.utils.quota import RequestQuota, quota, set_current_quota

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "MCP Rugido YT",
    instructions="MCP multi-tenant pra YouTube Data API, Analytics API e Reporting API.",
)

OAUTH_STATE_COOKIE = "mcp_rugido_oauth_state"


# ---------- Tools de auth/status ----------


@mcp.tool()
def youtube_auth_status() -> dict:
    """Retorna o status da sessão atual (canal vinculado, escopos, quota)."""
    return {
        "auth": auth.status(),
        "quota": quota.status(),
    }


# ---------- Imports das tools (acoplam @mcp.tool() decorators) ----------

from mcp_rugido_yt.tools import (
    analytics,  # noqa: E402, F401
    channel,  # noqa: E402, F401
    comments,  # noqa: E402, F401
    playlists,  # noqa: E402, F401
    publishing,  # noqa: E402, F401
    reporting,  # noqa: E402, F401
    search,  # noqa: E402, F401
    transcripts,  # noqa: E402, F401
)

# ---------- Rotas HTTP ----------


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def oauth_connect(request: Request) -> Response:
    state = secrets.token_urlsafe(32)
    auth_url = build_authorization_url(state)
    response = RedirectResponse(auth_url, status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


async def oauth_callback(request: Request) -> Response:
    error = request.query_params.get("error")
    if error:
        return _error_page(f"Google retornou erro: {error}", status=400)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)

    if not code or not state:
        return _error_page("Parâmetros ausentes.", status=400)
    if not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _error_page("State mismatch — possível CSRF.", status=400)

    try:
        result = exchange_code(code)
    except Exception as e:
        logger.exception("Falha ao trocar code por token")
        return _error_page(f"Falha ao trocar code: {e}", status=500)

    try:
        channel_id, handle, title = await _resolve_channel(
            result.refresh_token, result.scope
        )
    except Exception as e:
        logger.exception("Falha ao resolver canal do usuário")
        return _error_page(f"Falha ao resolver canal: {e}", status=500)

    async with session_factory()() as db:
        session_id = await create_session(
            db,
            channel_id=channel_id,
            channel_handle=handle,
            channel_title=title,
            google_email=result.google_email,
            refresh_token=result.refresh_token,
            scope=result.scope,
        )

    return _success_page(
        session_id=session_id,
        google_email=result.google_email,
        channel_title=title,
        channel_handle=handle,
    )


async def _resolve_channel(
    refresh_token: str, scope: str
) -> tuple[str, str | None, str | None]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    settings = get_settings()
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=scope.split() if scope else None,
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("Nenhum canal encontrado para esse usuário.")
    item = items[0]
    snippet = item.get("snippet", {})
    return item["id"], snippet.get("customUrl"), snippet.get("title")


def _success_page(
    *,
    session_id: str,
    google_email: str,
    channel_title: str | None,
    channel_handle: str | None,
) -> HTMLResponse:
    public_url = get_settings().public_base_url.rstrip("/")
    handle_html = f"(<code>{escape(channel_handle)}</code>)" if channel_handle else ""
    config_json = (
        "{\n"
        '  "mcpServers": {\n'
        '    "rugido-yt": {\n'
        f'      "url": "{escape(public_url)}/mcp",\n'
        f'      "headers": {{ "Authorization": "Bearer {escape(session_id)}" }}\n'
        "    }\n"
        "  }\n"
        "}"
    )
    body = f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><title>Conectado — MCP Rugido YT</title>
<style>
  body{{font-family:system-ui,-apple-system,sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.5}}
  code{{background:#eee;padding:2px 6px;border-radius:4px;word-break:break-all}}
  pre{{background:#1e1e1e;color:#eaeaea;padding:16px;border-radius:8px;overflow:auto;font-size:13px}}
  .ok{{color:#0a7d2c}}
</style></head><body>
  <h1 class="ok">Conectado</h1>
  <p>Conta <code>{escape(google_email)}</code> — canal <strong>{escape(channel_title or "?")}</strong> {handle_html}</p>
  <h3>1. Copie o session_id abaixo</h3>
  <pre>{escape(session_id)}</pre>
  <h3>2. Cole no seu cliente MCP</h3>
  <pre>{escape(config_json)}</pre>
  <p><strong>Guarde esse session_id</strong> — não conseguimos mostrar de novo. Se perder, refaça o consent.</p>
</body></html>"""
    return HTMLResponse(body)


def _error_page(msg: str, status: int = 400) -> HTMLResponse:
    body = (
        '<!doctype html><html><head><meta charset="utf-8"><title>Erro</title>'
        '<style>body{font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px}</style>'
        f"</head><body><h1>Erro</h1><p>{escape(msg)}</p></body></html>"
    )
    return HTMLResponse(body, status_code=status)


# ---------- Bearer middleware (apenas pro mount /mcp) ----------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        authz = request.headers.get("authorization", "")
        if not authz.lower().startswith("bearer "):
            return JSONResponse(
                {
                    "error": "missing_bearer",
                    "detail": "Authorization: Bearer <session_id> requerido",
                },
                status_code=401,
            )
        session_id = authz.split(" ", 1)[1].strip()

        async with session_factory()() as db:
            sess = await get_session_data(db, session_id)
            if sess is None:
                return JSONResponse(
                    {
                        "error": "invalid_session",
                        "detail": "session_id inválido ou revogado",
                    },
                    status_code=401,
                )

            set_current_session(sess)
            req_quota = RequestQuota(
                session_id=sess.session_id,
                used=sess.quota_used,
                reset_at=sess.quota_reset_at,
            )
            set_current_quota(req_quota)

            try:
                response = await call_next(request)
            finally:
                try:
                    if req_quota.dirty:
                        await db.execute(
                            update(McpSession)
                            .where(McpSession.session_id == sess.session_id)
                            .values(
                                quota_used=req_quota.used,
                                quota_reset_at=req_quota.reset_at,
                                last_used_at=datetime.now(timezone.utc),
                            )
                        )
                        await db.commit()
                    else:
                        await touch_session(db, sess.session_id)
                except Exception:
                    logger.exception("Falha ao persistir quota/last_used_at")
                set_current_session(None)
                set_current_quota(None)

            return response


# ---------- App ASGI ----------


@asynccontextmanager
async def lifespan(app: Starlette):
    init_engine()
    try:
        yield
    finally:
        await shutdown_engine()


def build_app() -> Starlette:
    mcp_app = mcp.streamable_http_app()
    mcp_app.add_middleware(BearerAuthMiddleware)

    return Starlette(
        debug=False,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/oauth/connect", oauth_connect, methods=["GET"]),
            Route("/oauth/callback", oauth_callback, methods=["GET"]),
            Mount("/mcp", app=mcp_app),
        ],
        lifespan=lifespan,
    )


def main():
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "mcp_rugido_yt.server:build_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
