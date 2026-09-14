from __future__ import annotations

from pathlib import Path
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message


class StaleTelegramFileId(RuntimeError):
    pass


class TelegramSender(Protocol):
    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None: ...

    async def send_photo(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...

    async def send_audio(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...

    async def send_document(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None: ...


class AiogramTelegramSender:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        await self._bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
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
        media = _media_input(path, file_id)
        try:
            message = await self._bot.send_photo(
                chat_id,
                media,
                caption=caption,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as error:
            _reraise_stale_file(error, file_id)
            raise
        return _photo_file_id(message)

    async def send_audio(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        media = _media_input(path, file_id)
        try:
            message = await self._bot.send_audio(
                chat_id,
                media,
                caption=caption,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as error:
            _reraise_stale_file(error, file_id)
            raise
        return None if message.audio is None else message.audio.file_id

    async def send_document(
        self,
        chat_id: int,
        path: Path,
        caption: str | None,
        reply_markup: InlineKeyboardMarkup | None = None,
        *,
        file_id: str | None = None,
    ) -> str | None:
        media = _media_input(path, file_id)
        try:
            message = await self._bot.send_document(
                chat_id,
                media,
                caption=caption,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as error:
            _reraise_stale_file(error, file_id)
            raise
        return None if message.document is None else message.document.file_id


def _media_input(path: Path, file_id: str | None) -> str | FSInputFile:
    if file_id:
        return file_id
    return FSInputFile(path)


def _photo_file_id(message: Message) -> str | None:
    if not message.photo:
        return None
    return message.photo[-1].file_id


def _reraise_stale_file(error: TelegramBadRequest, file_id: str | None) -> None:
    if file_id is None:
        return
    text = str(error).lower()
    if "file identifier" in text or "wrong file" in text:
        raise StaleTelegramFileId(str(error)) from error
