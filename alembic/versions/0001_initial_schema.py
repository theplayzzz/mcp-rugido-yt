"""initial schema — yt_mcp_sessions

Revision ID: 0001
Revises:
Create Date: 2026-04-30 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "yt_mcp_sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_handle", sa.String(length=128), nullable=True),
        sa.Column("channel_title", sa.String(length=256), nullable=True),
        sa.Column("google_email", sa.String(length=256), nullable=False),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("quota_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "quota_reset_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_yt_mcp_sessions_channel_id",
        "yt_mcp_sessions",
        ["channel_id"],
    )
    op.create_index(
        "ix_yt_mcp_sessions_google_email",
        "yt_mcp_sessions",
        ["google_email"],
    )


def downgrade() -> None:
    op.drop_index("ix_yt_mcp_sessions_google_email", table_name="yt_mcp_sessions")
    op.drop_index("ix_yt_mcp_sessions_channel_id", table_name="yt_mcp_sessions")
    op.drop_table("yt_mcp_sessions")
