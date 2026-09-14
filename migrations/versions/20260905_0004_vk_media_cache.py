"""add vk media attachment cache

Revision ID: 20260905_0004
Revises: 20260905_0003
Create Date: 2026-09-05 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260905_0004"
down_revision: str | None = "20260905_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vk_media_cache",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("community_id", sa.String(length=64), nullable=False),
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("media_kind", sa.String(length=32), nullable=False),
        sa.Column("attachment", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "media_kind IN ('photo', 'audio', 'document')",
            name="ck_vk_media_cache_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "community_id",
            "asset_sha256",
            "media_kind",
            name="uq_vk_media_cache_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("vk_media_cache")
