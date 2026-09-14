from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiogram.types import InlineKeyboardMarkup

from detective_bot.adapters.telegram.media import ResolvedMedia
from detective_bot.adapters.telegram.sender import StaleTelegramFileId


@dataclass(frozen=True, slots=True)
class RecordedSend:
    method: str
    chat_id: int
    text: str | None = None
    path: Path | None = None
    caption: str | None = None
    reply_markup: InlineKeyboardMarkup | None = None
    file_id: str | None = None


class RecordingTelegramSender:
    def __init__(self) -> None:
        self.calls: list[RecordedSend] = []
        self.stale_file_ids: set[str] = set()
        self.fail_next: Exception | None = None
        self.fail_always: Exception | None = None

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        self._raise_if_scripted()
        self.calls.append(
            RecordedSend(
                method="text",
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
            )
        )

    async def send_photo(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "photo",
            chat_id,
            path,
            caption,
            reply_markup,
            file_id=file_id,
        )

    async def send_audio(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "audio",
            chat_id,
            path,
            caption,
            reply_markup,
            file_id=file_id,
        )

    async def send_document(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "document",
            chat_id,
            path,
            caption,
            reply_markup,
            file_id=file_id,
        )

    async def _send_media(
        self,
        method: str,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None,
        *,
        file_id: str | None,
    ) -> str:
        self._raise_if_scripted()
        if file_id is not None and file_id in self.stale_file_ids:
            raise StaleTelegramFileId(file_id)
        recorded_id = file_id or f"uploaded:{method}:{path.name}"
        self.calls.append(
            RecordedSend(
                method=method,
                chat_id=chat_id,
                path=None if file_id else path,
                caption=caption,
                reply_markup=reply_markup,
                file_id=recorded_id,
            )
        )
        return recorded_id

    def _raise_if_scripted(self) -> None:
        if self.fail_always is not None:
            raise self.fail_always
        if self.fail_next is not None:
            error = self.fail_next
            self.fail_next = None
            raise error


class InMemoryTelegramMediaCache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str], str] = {}

    async def get(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> str | None:
        return self.entries.get((bot_id, asset_sha256, media_kind))

    async def put(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
        file_id: str,
        *,
        now: datetime,
    ) -> None:
        del now
        self.entries[(bot_id, asset_sha256, media_kind)] = file_id

    async def delete(
        self,
        bot_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> None:
        self.entries.pop((bot_id, asset_sha256, media_kind), None)


class MappingMediaResolver:
    def __init__(self, assets: dict[str, ResolvedMedia]) -> None:
        self.assets = assets

    async def resolve(self, session_id: str, asset_id: str) -> ResolvedMedia:
        del session_id
        return self.assets[asset_id]


class MappingMediaResolver:
    def __init__(self, assets: dict[str, ResolvedMedia]) -> None:
        self.assets = assets

    async def resolve(self, session_id: str, asset_id: str) -> ResolvedMedia:
        del session_id
        return self.assets[asset_id]
