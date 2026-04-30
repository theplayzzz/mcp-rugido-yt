"""Configura env vars de teste antes de qualquer import do app."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FERNET_KEY", "8gLR8R-AIBxz_TBPxs2yPrQ5JlDxrCnbg5xT-fhpv9o=")
os.environ.setdefault("MCP_PUBLIC_BASE_URL", "https://example.com")
os.environ.setdefault("YOUTUBE_API_KEY", "test-api-key")
