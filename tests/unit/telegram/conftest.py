from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from detective_bot.adapters.telegram.delivery import TelegramDeliveryService
from detective_bot.adapters.telegram.handlers import TelegramUpdateProcessor
from detective_bot.adapters.telegram.media import CatalogMediaResolver
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.application.service import ApplicationService
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from tests.fakes import (
    InMemoryTelegramMediaCache,
    InMemoryUnitOfWorkFactory,
    RecordingTelegramSender,
)


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
USER_ID = 11
CHAT_ID = 22


def make_user() -> User:
    return User(id=USER_ID, is_bot=False, first_name="Tester")


def make_chat(chat_type: str = "private") -> Chat:
    return Chat(id=CHAT_ID, type=chat_type)


def text_update(
    text: str,
    *,
    update_id: int = 1,
    chat_type: str = "private",
) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=NOW,
            chat=make_chat(chat_type),
            from_user=make_user(),
            text=text,
        ),
    )


def callback_update(data: str, *, update_id: int = 100) -> Update:
    message = Message(
        message_id=update_id,
        date=NOW,
        chat=make_chat(),
        from_user=make_user(),
        text="keyboard",
    )
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=make_user(),
            chat_instance="instance",
            data=data,
            message=message,
        ),
    )


@pytest.fixture
def telegram_harness() -> tuple[
    TelegramUpdateProcessor,
    RecordingTelegramSender,
    InMemoryUnitOfWorkFactory,
]:
    catalog = FileSystemGameCatalog(ROOT / "games")
    uow_factory = InMemoryUnitOfWorkFactory()
    sequence = count(1)
    service = ApplicationService(
        catalog=catalog,
        uow_factory=uow_factory,
        engine=GameEngine(),
        clock=lambda: NOW,
        session_id_factory=lambda: f"session-{next(sequence)}",
    )
    sender = RecordingTelegramSender()
    renderer = TelegramRenderer(
        sender=sender,
        resolver=CatalogMediaResolver(catalog, uow_factory),
        policy=TelegramMediaPolicy(document_asset_ids=frozenset({"report_asset"})),
        catalog=catalog,
        uow_factory=uow_factory,
        media_cache=InMemoryTelegramMediaCache(),
        bot_id="11",
        clock=lambda: NOW,
    )
    delivery = TelegramDeliveryService(
        uow_factory=uow_factory,
        renderer=renderer,
        catalog=catalog,
        clock=lambda: NOW,
    )
    processor = TelegramUpdateProcessor(service, renderer, uow_factory, delivery)
    return processor, sender, uow_factory
