"""Tests for auth module (Web flow multi-tenant)."""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FERNET_KEY", "8gLR8R-AIBxz_TBPxs2yPrQ5JlDxrCnbg5xT-fhpv9o=")
os.environ.setdefault("MCP_PUBLIC_BASE_URL", "https://example.com")

from mcp_rugido_yt.auth import (  # noqa: E402
    GOOGLE_TOKEN_URI,
    SCOPES,
    YouTubeAuth,
    build_authorization_url,
    credentials_for_session,
)
from mcp_rugido_yt.sessions import SessionData  # noqa: E402


def _make_session(refresh_token: str = "rt_x") -> SessionData:
    return SessionData(
        session_id="ymp_test",
        channel_id="UC_test",
        channel_handle="@test",
        channel_title="Test Channel",
        google_email="test@example.com",
        refresh_token=refresh_token,
        scope=" ".join(SCOPES),
        quota_used=0,
        quota_reset_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


def test_authorization_url_contains_required_params():
    url = build_authorization_url(state="abc123")
    assert "accounts.google.com" in url
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=abc123" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Foauth%2Fcallback" in url


def test_credentials_for_session_uses_refresh_token():
    session = _make_session("my_refresh_token")
    creds = credentials_for_session(session)
    assert creds.refresh_token == "my_refresh_token"
    assert creds.client_id == "test-client-id"
    assert creds.client_secret == "test-client-secret"
    assert creds.token_uri == GOOGLE_TOKEN_URI


def test_youtube_auth_holds_session():
    session = _make_session()
    yt_auth = YouTubeAuth(session)
    assert yt_auth.session is session
    assert yt_auth._creds.refresh_token == "rt_x"
