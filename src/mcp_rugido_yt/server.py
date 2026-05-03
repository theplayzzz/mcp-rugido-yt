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


async def home(request: Request) -> Response:
    """Página inicial — explica o que é e linka pro consent."""
    verif_token = get_settings().google_site_verification
    verif_meta = (
        f'<meta name="google-site-verification" content="{escape(verif_token)}">\n'
        if verif_token
        else ""
    )
    body = f"""<!doctype html>
<html lang="pt-BR"><head>
{verif_meta}<meta charset="utf-8"><title>MCP Rugido YT</title>
<style>
  body{{font-family:system-ui,-apple-system,sans-serif;max-width:720px;margin:48px auto;padding:0 16px;line-height:1.6;color:#222}}
  h1{{margin-bottom:8px}}
  .lead{{color:#555;font-size:18px}}
  a{{color:#0a64d1}}
  ul{{padding-left:20px}}
  .cta{{display:inline-block;background:#0a64d1;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;margin-top:16px}}
  .cta:hover{{background:#084ea3}}
  footer{{margin-top:48px;padding-top:16px;border-top:1px solid #eee;color:#666;font-size:13px}}
</style></head><body>
  <h1>MCP Rugido YT</h1>
  <p class="lead">Servidor MCP (Model Context Protocol) para análise de canais do YouTube via Claude.</p>
  <h2>O que faz</h2>
  <p>Conecta sua conta do YouTube ao Claude Code/Desktop e expõe ferramentas de leitura para:</p>
  <ul>
    <li>Métricas Analytics — performance, retenção, audiência, demographics, geografia, receita</li>
    <li>Listagem de vídeos, canais, playlists e comentários (apenas leitura)</li>
    <li>Search, trending, sugestões de SEO</li>
    <li>Transcrições e captions</li>
    <li>Bulk reporting via Reporting API</li>
  </ul>
  <p>O servidor <strong>não publica, não comenta, não modifica</strong> nada na sua conta — somente leitura.</p>
  <p><a class="cta" href="/oauth/connect">Conectar minha conta do YouTube</a></p>
  <footer>
    Operado pelo Grupo Rugido. Uso interno. Veja
    <a href="/privacy">Política de Privacidade</a> e
    <a href="/terms">Termos de Uso</a>.
  </footer>
</body></html>"""
    return HTMLResponse(body)


async def privacy(request: Request) -> Response:
    body = """<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><title>Política de Privacidade — MCP Rugido YT</title>
<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6;color:#222} h2{margin-top:32px}</style>
</head><body>
  <h1>Política de Privacidade — MCP Rugido YT</h1>
  <p><em>Última atualização: 03 de maio de 2026</em></p>

  <h2>1. Quem somos</h2>
  <p>O MCP Rugido YT é um servidor operado pelo Grupo Rugido para uso interno e de parceiros, que conecta canais do YouTube ao Claude (Anthropic) via protocolo MCP para análise de métricas.</p>

  <h2>2. Que dados coletamos</h2>
  <p>Quando você autoriza o app via Google OAuth, recebemos:</p>
  <ul>
    <li>Seu endereço de e-mail Google (para identificar a sessão)</li>
    <li>ID, título e handle do seu canal do YouTube</li>
    <li>Token de atualização (refresh_token) emitido pelo Google, criptografado em repouso com chave Fernet</li>
  </ul>
  <p>Quando você usa as ferramentas via Claude, dados do seu canal (métricas, listagens, transcrições) são acessados em tempo real do Google e devolvidos ao Claude. <strong>Não armazenamos esses dados em nosso banco.</strong></p>

  <h2>3. Como usamos os dados</h2>
  <ul>
    <li>O refresh_token é usado exclusivamente para acessar a API do YouTube em seu nome quando você invoca uma ferramenta MCP</li>
    <li>Não compartilhamos com terceiros</li>
    <li>Não usamos para publicidade, profiling ou treino de IA</li>
    <li>Não combinamos com dados de outras fontes</li>
  </ul>

  <h2>4. Escopos solicitados e por quê</h2>
  <ul>
    <li><code>youtube.readonly</code> — listar vídeos, ver metadados do canal, ler comentários e playlists</li>
    <li><code>yt-analytics.readonly</code> — métricas de performance, audiência, retenção</li>
    <li><code>openid</code> + <code>userinfo.email</code> — identificar a sessão pelo e-mail</li>
  </ul>
  <p>Não solicitamos escopos de escrita, upload, comentário ou modificação.</p>

  <h2>5. Retenção</h2>
  <p>Mantemos o refresh_token enquanto sua sessão estiver ativa. Você pode revogar a qualquer momento em <a href="https://myaccount.google.com/permissions" target="_blank">myaccount.google.com/permissions</a>. Após revogação, o token fica inválido e podemos remover o registro a pedido.</p>

  <h2>6. Segurança</h2>
  <ul>
    <li>Refresh tokens criptografados em repouso (Fernet/AES-128-CBC + HMAC)</li>
    <li>HTTPS obrigatório (Let's Encrypt)</li>
    <li>Sessões protegidas por bearer token opaco</li>
  </ul>

  <h2>7. Limites de uso conforme Google API Services User Data Policy</h2>
  <p>O uso de dados do Google pelo MCP Rugido YT respeita a <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank">Google API Services User Data Policy</a>, incluindo os requisitos de Limited Use.</p>

  <h2>8. Contato</h2>
  <p>Dúvidas ou solicitação de remoção: <a href="mailto:lucas3k@rugido.com">lucas3k@rugido.com</a></p>
</body></html>"""
    return HTMLResponse(body)


async def terms(request: Request) -> Response:
    body = """<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><title>Termos de Uso — MCP Rugido YT</title>
<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6;color:#222} h2{margin-top:32px}</style>
</head><body>
  <h1>Termos de Uso — MCP Rugido YT</h1>
  <p><em>Última atualização: 03 de maio de 2026</em></p>

  <h2>1. Aceitação</h2>
  <p>Ao autorizar sua conta do YouTube no MCP Rugido YT, você concorda com estes Termos.</p>

  <h2>2. Uso permitido</h2>
  <p>O serviço é fornecido para análise de métricas do seu próprio canal do YouTube, exclusivamente para fins legítimos relacionados ao seu negócio ou conteúdo.</p>

  <h2>3. Uso não permitido</h2>
  <ul>
    <li>Tentar acessar dados de canais que você não controla</li>
    <li>Usar para spam, manipulação de métricas ou violação dos Termos do YouTube</li>
    <li>Engenharia reversa do servidor ou tentativa de extrair tokens de outros usuários</li>
  </ul>

  <h2>4. Disponibilidade</h2>
  <p>Servimos "as is", sem garantia de uptime. Quotas da YouTube API podem limitar uso em dias de pico.</p>

  <h2>5. Limitação de responsabilidade</h2>
  <p>O Grupo Rugido não se responsabiliza por decisões tomadas com base nas análises geradas, falhas de terceiros (Google, Anthropic) ou indisponibilidade do serviço.</p>

  <h2>6. Encerramento</h2>
  <p>Você pode revogar acesso a qualquer momento em <a href="https://myaccount.google.com/permissions" target="_blank">myaccount.google.com/permissions</a>. Reservamos o direito de suspender sessões que violem estes Termos.</p>

  <h2>7. Alterações</h2>
  <p>Estes Termos podem ser atualizados. Mudanças significativas serão comunicadas a usuários ativos pelo e-mail registrado.</p>

  <h2>8. Contato</h2>
  <p><a href="mailto:lucas3k@rugido.com">lucas3k@rugido.com</a></p>
</body></html>"""
    return HTMLResponse(body)


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

    app.add_route("/", home, methods=["GET"])
    app.add_route("/privacy", privacy, methods=["GET"])
    app.add_route("/terms", terms, methods=["GET"])
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
