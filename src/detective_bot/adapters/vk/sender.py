from __future__ import annotations

from pathlib import Path
from typing import Protocol
import random

from vkbottle import (
    API,
    DocMessagesUploader,
    PhotoMessageUploader,
    VKAPIError,
    VoiceMessageUploader,
)


class StaleVkAttachment(RuntimeError):
    pass


VK_FLOOD_CODES = frozenset({6, 9})


class VkSender(Protocol):
    async def send_text(
        self,
        peer_id: int,
        text: str,
        keyboard: str | None = None,
    ) -> None: ...

    async def send_photo(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...

    async def send_audio(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...

    async def send_document(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...


class VkbottleVkSender:
    def __init__(self, api: API, *, community_id: str | None = None) -> None:
        self._api = api
        self._community_id = int(community_id) if community_id else None
        self._photos = PhotoMessageUploader(api)
        self._docs = DocMessagesUploader(api)
        self._voices = VoiceMessageUploader(api)

    async def send_text(
        self,
        peer_id: int,
        text: str,
        keyboard: str | None = None,
    ) -> None:
        await self._send_message(peer_id, message=text, keyboard=keyboard)

    async def send_photo(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        attachment = file_id
        if attachment is None:
            attachment = await self._photos.upload(str(path), peer_id=peer_id)
        await self._send_media(peer_id, attachment, caption, keyboard, cached=file_id)
        return attachment

    async def send_audio(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        attachment = file_id
        if attachment is None:
            attachment = await self._voices.upload(
                file_source=_existing_file_source(path),
                group_id=self._community_id,
                peer_id=peer_id,
            )
        await self._send_media(peer_id, attachment, caption, keyboard, cached=file_id)
        return attachment

    async def send_document(
        self,
        peer_id: int,
        path: Path,
        caption: str | None,
        keyboard: str | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        attachment = file_id
        if attachment is None:
            attachment = await self._docs.upload(
                file_source=_existing_file_source(path),
                group_id=self._community_id,
                peer_id=peer_id,
            )
        await self._send_media(peer_id, attachment, caption, keyboard, cached=file_id)
        return attachment

    async def _send_media(
        self,
        peer_id: int,
        attachment: str,
        caption: str | None,
        keyboard: str | None,
        *,
        cached: str | None,
    ) -> None:
        try:
            await self._send_message(
                peer_id,
                message=caption,
                keyboard=keyboard,
                attachment=attachment,
            )
        except VKAPIError as error:
            if cached is not None and error.code not in VK_FLOOD_CODES:
                raise StaleVkAttachment(str(error)) from error
            raise

    async def _send_message(
        self,
        peer_id: int,
        *,
        message: str | None = None,
        keyboard: str | None = None,
        attachment: str | None = None,
    ) -> None:
        params: dict[str, object] = {
            "peer_id": peer_id,
            "random_id": random.randint(1, 2_147_483_647),
        }
        if message:
            params["message"] = message
        if keyboard is not None:
            params["keyboard"] = keyboard
        if attachment is not None:
            params["attachment"] = attachment
        await self._api.messages.send(**params)


def _existing_file_source(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"vk media file is missing: {path}")
    return str(path)
