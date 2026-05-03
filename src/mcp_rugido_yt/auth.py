"""Autenticação OAuth 2.0 multi-tenant para as APIs do YouTube.

Ao contrário do fluxo Desktop original, aqui usamos o **Web flow**:
- O servidor monta a URL de consent
- O Google redireciona pro nosso /oauth/callback após o consent
- Trocamos o code por refresh_token e gravamos no banco (criptografado)
- Cada chamada de tool MCP recebe um session_id no Authorization Bearer e
  monta as credenciais Google em memória a partir do refresh_token armazenado
"""

from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from mcp_rugido_yt.config import get_settings
from mcp_rugido_yt.sessions import SessionData

SCOPES = [
    # Read-only do canal (sensitive). Cobre listing de vídeos, channel info,
    # playlists (read), comentários (read), captions/transcripts.
    "https://www.googleapis.com/auth/youtube.readonly",
    # Analytics — métricas de performance, audience, retention, traffic sources.
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # Identidade do usuário pra resolver o canal e gravar email na sessão.
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]
# NOTA sobre escopos removidos pra evitar bloqueio do consent Google:
#   - `youtube` + `youtube.upload` (restricted): exigem Verificação + Security
#     Assessment (US$ 4-15k). Tools afetadas em publishing.py, comments write,
#     playlists write — também removidas das listagens MCP.
#   - `yt-analytics-monetary.readonly` (sensitive mais protegido): bloqueava
#     contas com flag de risco mesmo após Publish em Production. Tools
#     afetadas: youtube_analytics_revenue e youtube_analytics_revenue_by_video.
# Pra reativar qualquer um, re-incluir aqui + no consent screen do Console e
# submeter Verificação Google.

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class TokenExchangeResult:
    refresh_token: str
    scope: str
    google_email: str


def _client_config() -> dict:
    settings = get_settings()
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [settings.oauth_redirect_uri],
        }
    }


def build_authorization_url(state: str) -> tuple[str, str]:
    """Monta URL pro qual o usuário é redirecionado pra dar consent.

    access_type=offline + prompt=consent são essenciais — sem prompt=consent o
    Google não devolve refresh_token na segunda autorização do mesmo usuário.

    Retorna (auth_url, code_verifier). O code_verifier precisa ser persistido
    entre /oauth/connect e /oauth/callback pro PKCE funcionar (cookie no MCP).
    """
    settings = get_settings()
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, autogenerate_code_verifier=True
    )
    flow.redirect_uri = settings.oauth_redirect_uri
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return auth_url, flow.code_verifier


def exchange_code(code: str, *, code_verifier: str | None = None) -> TokenExchangeResult:
    """Troca o code retornado pelo Google por refresh_token + identidade."""
    settings = get_settings()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.oauth_redirect_uri
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials  # type: ignore[assignment]

    if not creds.refresh_token:
        raise AuthError(
            "Google não retornou refresh_token. "
            "O usuário pode ter revogado o app antes de tentar de novo, "
            "ou prompt=consent não foi enviado."
        )

    email = _email_from_credentials(creds)
    scope = " ".join(creds.scopes or SCOPES)

    return TokenExchangeResult(
        refresh_token=creds.refresh_token,
        scope=scope,
        google_email=email,
    )


def _email_from_credentials(creds: Credentials) -> str:
    import base64
    import json

    id_token = getattr(creds, "id_token", None)
    if not id_token:
        raise AuthError("id_token ausente — scope 'openid email' está incluído?")
    parts = id_token.split(".")
    if len(parts) < 2:
        raise AuthError("id_token malformado")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))
    email = data.get("email")
    if not email:
        raise AuthError("email ausente no id_token")
    return email


def credentials_for_session(session: SessionData) -> Credentials:
    """Monta Credentials Google a partir de uma SessionData.

    googleapiclient cuida do refresh do access_token sob demanda.
    """
    settings = get_settings()
    return Credentials(
        token=None,
        refresh_token=session.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=session.scope.split() if session.scope else SCOPES,
    )


class YouTubeAuth:
    """Builder de service clients escopado a uma sessão MCP."""

    def __init__(self, session: SessionData):
        self.session = session
        self._creds = credentials_for_session(session)

    def build_youtube_service(self):
        return build("youtube", "v3", credentials=self._creds, cache_discovery=False)

    def build_youtube_analytics_service(self):
        return build(
            "youtubeAnalytics", "v2", credentials=self._creds, cache_discovery=False
        )

    def build_youtube_reporting_service(self):
        return build(
            "youtubereporting", "v1", credentials=self._creds, cache_discovery=False
        )

    def build_public_youtube_service(self):
        api_key = get_settings().youtube_api_key
        if not api_key:
            raise AuthError("YOUTUBE_API_KEY não definida.")
        return build("youtube", "v3", developerKey=api_key, cache_discovery=False)
