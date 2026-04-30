"""Tests for RequestQuota."""

import os
from datetime import datetime, timedelta, timezone

import pytest

# Settings precisa estar populada antes de importar quota
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x")
os.environ.setdefault("GOOGLE_CLIENT_ID", "x")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "x")
os.environ.setdefault("FERNET_KEY", "8gLR8R-AIBxz_TBPxs2yPrQ5JlDxrCnbg5xT-fhpv9o=")
os.environ.setdefault("MCP_PUBLIC_BASE_URL", "https://example.com")

from mcp_rugido_yt.utils.quota import (  # noqa: E402
    QuotaExhaustedError,
    RequestQuota,
)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=1)


def test_initial_state():
    q = RequestQuota("ymp_x", used=0, reset_at=_future(), daily_limit=10_000)
    assert q.used == 0
    assert q.remaining == 10_000
    assert q.dirty is False


def test_consume_list():
    q = RequestQuota("ymp_x", used=0, reset_at=_future())
    q.consume("list")
    assert q.used == 1
    assert q.dirty is True


def test_consume_search():
    q = RequestQuota("ymp_x", used=0, reset_at=_future())
    q.consume("search")
    assert q.used == 100


def test_consume_multiple():
    q = RequestQuota("ymp_x", used=0, reset_at=_future())
    q.consume("list")
    q.consume("search")
    q.consume("list", count=3)
    assert q.used == 104


def test_starts_with_existing_usage():
    q = RequestQuota("ymp_x", used=500, reset_at=_future())
    assert q.used == 500
    assert q.dirty is False
    q.consume("list")
    assert q.dirty is True


def test_exhaust_quota():
    q = RequestQuota("ymp_x", used=0, reset_at=_future(), daily_limit=50)
    q.consume("list", count=50)
    with pytest.raises(QuotaExhaustedError) as exc_info:
        q.consume("list")
    assert exc_info.value.used == 50
    assert exc_info.value.limit == 50


def test_resets_when_past_reset_at():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    q = RequestQuota("ymp_x", used=9999, reset_at=past, daily_limit=10_000)
    # Reset aconteceu na construção porque reset_at estava no passado
    assert q.used == 0


def test_unknown_operation_defaults_to_1():
    q = RequestQuota("ymp_x", used=0, reset_at=_future())
    q.consume("some_unknown_op")
    assert q.used == 1


def test_status():
    q = RequestQuota("ymp_x", used=0, reset_at=_future(), daily_limit=10_000)
    q.consume("search")
    status = q.status()
    assert status["used"] == 100
    assert status["remaining"] == 9_900
    assert status["limit"] == 10_000
    assert "reset_at" in status
