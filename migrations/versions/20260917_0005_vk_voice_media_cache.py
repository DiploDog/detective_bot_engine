"""allow VK voice attachments in media cache

Revision ID: 20260917_0005
Revises: 20260905_0004
Create Date: 2026-09-17 18:30:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260917_0005"
down_revision: str | None = "20260905_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_vk_media_cache_kind",
        "vk_media_cache",
        type_="check",
    )
    op.create_check_constraint(
        "ck_vk_media_cache_kind",
        "vk_media_cache",
        "media_kind IN ('photo', 'audio', 'document', 'voice')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM vk_media_cache WHERE media_kind = 'voice'")
    op.drop_constraint(
        "ck_vk_media_cache_kind",
        "vk_media_cache",
        type_="check",
    )
    op.create_check_constraint(
        "ck_vk_media_cache_kind",
        "vk_media_cache",
        "media_kind IN ('photo', 'audio', 'document')",
    )
