"""add telegram media file_id cache

Revision ID: 20260905_0003
Revises: 20260905_0002
Create Date: 2026-09-05 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260905_0003"
down_revision: str | None = "20260905_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_media_cache",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("bot_id", sa.String(length=64), nullable=False),
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("media_kind", sa.String(length=32), nullable=False),
        sa.Column("file_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "media_kind IN ('photo', 'audio', 'document')",
            name="ck_telegram_media_cache_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bot_id",
            "asset_sha256",
            "media_kind",
            name="uq_telegram_media_cache_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_media_cache")
