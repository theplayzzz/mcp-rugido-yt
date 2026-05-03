"""Settings carregadas a partir de variáveis de ambiente."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Server
    host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    port: int = Field(default=8000, alias="MCP_PORT")
    public_base_url: str = Field(
        ...,
        alias="MCP_PUBLIC_BASE_URL",
        description="URL pública (https) onde o servidor é acessível. Usada para montar o redirect_uri do Google.",
    )

    # Database
    database_url: str = Field(
        ...,
        alias="DATABASE_URL",
        description="postgresql+asyncpg://user:pass@host:5432/dbname",
    )

    # Google OAuth
    google_client_id: str = Field(..., alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., alias="GOOGLE_CLIENT_SECRET")

    # Crypto
    fernet_key: str = Field(
        ...,
        alias="FERNET_KEY",
        description=(
            "Chave Fernet base64 urlsafe de 32 bytes. Gere com: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        ),
    )

    # Optional
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    daily_quota_limit: int = Field(default=10_000, alias="DAILY_QUOTA_LIMIT")

    # Google Site Verification — token do meta tag (sem o "google-site-verification=").
    # Setar quando for verificar propriedade do domínio no Search Console
    # via HTML meta tag method.
    google_site_verification: str | None = Field(
        default=None, alias="GOOGLE_SITE_VERIFICATION"
    )

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/oauth/callback"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
