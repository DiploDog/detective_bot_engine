from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from detective_bot.adapters.vk.sender import StaleVkAttachment


@dataclass(frozen=True, slots=True)
class RecordedVkSend:
    method: str
    peer_id: int
    text: str | None = None
    path: Path | None = None
    caption: str | None = None
    keyboard: str | None = None
    file_id: str | None = None


class RecordingVkSender:
    def __init__(self) -> None:
        self.calls: list[RecordedVkSend] = []
        self.stale_file_ids: set[str] = set()
        self.fail_next: Exception | None = None
        self.fail_always: Exception | None = None

    async def send_text(
        self,
        peer_id: int,
        text: str,
        keyboard: str | None = None,
    ) -> None:
        self._raise_if_scripted()
        self.calls.append(
            RecordedVkSend(
                method="text",
                peer_id=peer_id,
                text=text,
                keyboard=keyboard,
            )
        )

    async def send_photo(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "photo",
            peer_id,
            path,
            caption,
            keyboard,
            file_id=file_id,
        )

    async def send_audio(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "audio",
            peer_id,
            path,
            caption,
            keyboard,
            file_id=file_id,
        )

    async def send_document(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        return await self._send_media(
            "document",
            peer_id,
            path,
            caption,
            keyboard,
            file_id=file_id,
        )

    async def _send_media(
        self,
        method: str,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None,
        *,
        file_id: str | None,
    ) -> str:
        self._raise_if_scripted()
        if file_id is not None and file_id in self.stale_file_ids:
            raise StaleVkAttachment(file_id)
        recorded_id = file_id or f"uploaded:{method}:{path.name}"
        self.calls.append(
            RecordedVkSend(
                method=method,
                peer_id=peer_id,
                path=None if file_id else path,
                caption=caption,
                keyboard=keyboard,
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


class InMemoryVkMediaCache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str], str] = {}

    async def get(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> str | None:
        return self.entries.get((community_id, asset_sha256, media_kind))

    async def put(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
        attachment: str,
        *,
        now: datetime,
    ) -> None:
        del now
        self.entries[(community_id, asset_sha256, media_kind)] = attachment

    async def delete(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> None:
        self.entries.pop((community_id, asset_sha256, media_kind), None)
