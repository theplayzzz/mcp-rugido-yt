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
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import update
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from mcp_rugido_yt.auth import build_authorization_url, exchange_code
from mcp_rugido_yt.config import get_settings
from mcp_rugido_yt.db import init_engine, session_factory, shutdown_engine
from mcp_rugido_yt.db.models import McpSession
from mcp_rugido_yt.runtime import auth, set_current_session
from mcp_rugido_yt.sessions import create_session, get_session_data, touch_session
from mcp_rugido_yt.utils.quota import RequestQuota, quota, set_current_quota

logger = logging.getLogger(__name__)

_public_host = urlparse(get_settings().public_base_url).netloc

mcp = FastMCP(
    "MCP Rugido YT",
    instructions="MCP multi-tenant pra YouTube Data API, Analytics API e Reporting API.",
    transport_security=TransportSecuritySettings(
        # Sem isso o MCP SDK retorna 421 "Invalid Host header" pra qualquer
        # request fora de localhost (proteção contra DNS rebinding).
        allowed_hosts=[_public_host, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[get_settings().public_base_url.rstrip("/")],
    ),
)

OAUTH_STATE_COOKIE = "mcp_rugido_oauth_state"
OAUTH_PKCE_COOKIE = "mcp_rugido_oauth_pkce"


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
    reporting,  # noqa: E402, F401
    search,  # noqa: E402, F401
    transcripts,  # noqa: E402, F401
)

# ---------- Rotas HTTP ----------


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def oauth_connect(request: Request) -> Response:
    state = secrets.token_urlsafe(32)
    auth_url, code_verifier = build_authorization_url(state)
    response = RedirectResponse(auth_url, status_code=302)
    cookie_kwargs = dict(max_age=600, httponly=True, secure=True, samesite="lax")
    response.set_cookie(OAUTH_STATE_COOKIE, state, **cookie_kwargs)
    response.set_cookie(OAUTH_PKCE_COOKIE, code_verifier, **cookie_kwargs)
    return response


async def oauth_callback(request: Request) -> Response:
    error = request.query_params.get("error")
    if error:
        return _error_page(f"Google retornou erro: {error}", status=400)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    cookie_verifier = request.cookies.get(OAUTH_PKCE_COOKIE)

    if not code or not state:
        return _error_page("Parâmetros ausentes.", status=400)
    if not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _error_page("State mismatch — possível CSRF.", status=400)
    if not cookie_verifier:
        return _error_page(
            "PKCE verifier ausente. Cookies bloqueados? Tente de novo em uma janela limpa.",
            status=400,
        )

    try:
        result = exchange_code(code, code_verifier=cookie_verifier)
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
    mcp_url = f"{public_url}/mcp"
    handle_html = (
        f' (<code>{escape(channel_handle)}</code>)' if channel_handle else ""
    )

    cli_command = (
        f'claude mcp add --transport http rugido-yt {mcp_url} '
        f'--header "Authorization: Bearer {session_id}"'
    )

    desktop_json = (
        "{\n"
        '  "mcpServers": {\n'
        '    "rugido-yt": {\n'
        f'      "url": "{mcp_url}",\n'
        f'      "headers": {{ "Authorization": "Bearer {session_id}" }}\n'
        "    }\n"
        "  }\n"
        "}"
    )

    handoff_prompt = (
        f"Roda este comando exatamente como está e depois `claude mcp list`:\n\n"
        f"{cli_command}\n\n"
        "Confirme que apareceu como Connected e me mostre as tools listadas."
    )

    body = f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><title>Conectado — MCP Rugido YT</title>
<style>
  :root {{ color-scheme: light dark; }}
  body{{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.55;color:#222}}
  h1{{margin:0 0 4px}}
  h2{{margin-top:32px;font-size:18px;border-bottom:1px solid #ddd;padding-bottom:6px}}
  code{{background:#eef;padding:2px 6px;border-radius:4px;word-break:break-all;font-size:13px}}
  pre{{background:#1e1e1e;color:#eaeaea;padding:14px 16px;border-radius:8px;overflow:auto;font-size:13px;line-height:1.45;position:relative}}
  pre button{{position:absolute;top:8px;right:8px;background:#444;color:#eee;border:0;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer}}
  pre button:hover{{background:#666}}
  pre button.copied{{background:#0a7d2c}}
  .ok{{color:#0a7d2c}}
  .meta{{color:#555;font-size:14px;margin:0 0 4px}}
  .warn{{background:#fff8e1;border-left:4px solid #f0b400;padding:10px 14px;margin:16px 0;border-radius:4px;font-size:14px}}
  details{{margin-top:8px}}
  summary{{cursor:pointer;color:#0366d6;font-size:14px}}
</style></head><body>
  <h1 class="ok">✓ Conectado</h1>
  <p class="meta">Conta <code>{escape(google_email)}</code></p>
  <p class="meta">Canal <strong>{escape(channel_title or "?")}</strong>{handle_html}</p>

  <h2>Seu session_id</h2>
  <pre id="sid"><button data-target="sid">copiar</button>{escape(session_id)}</pre>
  <div class="warn">Guarde em local seguro. <strong>Não conseguimos mostrar de novo.</strong> Se perder, é só voltar em <code>/oauth/connect</code> e refazer.</div>

  <h2>Instalar no Claude Code (recomendado)</h2>
  <p>Cole este comando num terminal onde o <code>claude</code> CLI esteja instalado:</p>
  <pre id="cli"><button data-target="cli">copiar</button>{escape(cli_command)}</pre>
  <p>Reinicie o Claude Code. As 40 ferramentas <code>youtube_*</code> aparecem automaticamente.</p>

  <details>
    <summary>Prompt pronto pra mandar pro próprio Claude Code instalar</summary>
    <p>Cole isso na conversa do Claude Code que ele resolve a instalação sozinho:</p>
    <pre id="handoff"><button data-target="handoff">copiar</button>{escape(handoff_prompt)}</pre>
  </details>

  <h2>Alternativa — Claude Desktop / arquivo .mcp.json</h2>
  <p>Adicione ao <code>claude_desktop_config.json</code> ou a um <code>.mcp.json</code> na raiz do projeto:</p>
  <pre id="json"><button data-target="json">copiar</button>{escape(desktop_json)}</pre>

  <h2>Próximo passo</h2>
  <p>Dentro do Claude Code, peça algo como <em>"liste meus 5 vídeos mais recentes do YouTube"</em> — ele chama <code>youtube_list_videos</code> com seu token e devolve os dados do canal acima.</p>

  <script>
    document.querySelectorAll('pre button').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        const target = document.getElementById(btn.dataset.target);
        const text = target.innerText.replace(/^copiar\\n?/, '').trim();
        try {{
          await navigator.clipboard.writeText(text);
          btn.textContent = 'copiado ✓';
          btn.classList.add('copied');
          setTimeout(() => {{
            btn.textContent = 'copiar';
            btn.classList.remove('copied');
          }}, 2000);
        }} catch (e) {{
          btn.textContent = 'falhou';
        }}
      }});
    }});
  </script>
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
        # Bearer auth aplica somente ao endpoint MCP, não às rotas auxiliares.
        if request.url.path != "/mcp":
            return await call_next(request)

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


def build_app() -> Starlette:
    """Constrói o app ASGI final.

    Estratégia: usa o `mcp.streamable_http_app()` como base (que tem o lifespan
    do FastMCP, necessário pro task group do session manager). Anexa as rotas
    auxiliares (/health, /oauth/*) no mesmo app — evita Mount aninhado, que
    isolaria o lifespan e quebraria o handler MCP.
    """
    app = mcp.streamable_http_app()

    app.add_route("/health", health, methods=["GET"])
    app.add_route("/oauth/connect", oauth_connect, methods=["GET"])
    app.add_route("/oauth/callback", oauth_callback, methods=["GET"])

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def wrapped_lifespan(_app: Starlette):
        init_engine()
        try:
            async with original_lifespan(_app):
                yield
        finally:
            await shutdown_engine()

    app.router.lifespan_context = wrapped_lifespan

    app.add_middleware(BearerAuthMiddleware)

    return app


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
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
