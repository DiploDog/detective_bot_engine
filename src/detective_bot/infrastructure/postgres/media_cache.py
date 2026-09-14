from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.infrastructure.postgres.models import (
    TelegramMediaCacheRow,
    VkMediaCacheRow,
)


class PostgresTelegramMediaCache:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> str | None:
        async with self._session_factory() as db:
            file_id = (
                await db.execute(
                    select(TelegramMediaCacheRow.file_id).where(
                        TelegramMediaCacheRow.bot_id == bot_id,
                        TelegramMediaCacheRow.asset_sha256 == asset_sha256,
                        TelegramMediaCacheRow.media_kind == media_kind,
                    )
                )
            ).scalar_one_or_none()
        return file_id

    async def put(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
        file_id: str,
        *,
        now: datetime,
    ) -> None:
        async with self._session_factory() as db:
            await db.execute(
                insert(TelegramMediaCacheRow)
                .values(
                    bot_id=bot_id,
                    asset_sha256=asset_sha256,
                    media_kind=media_kind,
                    file_id=file_id,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_telegram_media_cache_identity",
                    set_={
                        "file_id": file_id,
                        "updated_at": now,
                    },
                )
            )
            await db.commit()

    async def delete(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> None:
        async with self._session_factory() as db:
            await db.execute(
                delete(TelegramMediaCacheRow).where(
                    TelegramMediaCacheRow.bot_id == bot_id,
                    TelegramMediaCacheRow.asset_sha256 == asset_sha256,
                    TelegramMediaCacheRow.media_kind == media_kind,
                )
            )
            await db.commit()


class PostgresVkMediaCache:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> str | None:
        async with self._session_factory() as db:
            attachment = (
                await db.execute(
                    select(VkMediaCacheRow.attachment).where(
                        VkMediaCacheRow.community_id == community_id,
                        VkMediaCacheRow.asset_sha256 == asset_sha256,
                        VkMediaCacheRow.media_kind == media_kind,
                    )
                )
            ).scalar_one_or_none()
        return attachment

    async def put(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
        attachment: str,
        *,
        now: datetime,
    ) -> None:
        async with self._session_factory() as db:
            await db.execute(
                insert(VkMediaCacheRow)
                .values(
                    community_id=community_id,
                    asset_sha256=asset_sha256,
                    media_kind=media_kind,
                    attachment=attachment,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_vk_media_cache_identity",
                    set_={
                        "attachment": attachment,
                        "updated_at": now,
                    },
                )
            )
            await db.commit()

    async def delete(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> None:
        async with self._session_factory() as db:
            await db.execute(
                delete(VkMediaCacheRow).where(
                    VkMediaCacheRow.community_id == community_id,
                    VkMediaCacheRow.asset_sha256 == asset_sha256,
                    VkMediaCacheRow.media_kind == media_kind,
                )
            )
            await db.commit()
