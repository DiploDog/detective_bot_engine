from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path
import json

import pytest
from vkbottle.bot import Message, MessageEvent
from vkbottle_types.events.objects.group_event_objects import MessageEventObject

from detective_bot.adapters.media import CatalogMediaResolver
from detective_bot.adapters.vk.delivery import VkDeliveryService
from detective_bot.adapters.vk.handlers import VkUpdateProcessor
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.application.service import ApplicationService
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from tests.fakes import InMemoryUnitOfWorkFactory, InMemoryVkMediaCache, RecordingVkSender


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
USER_ID = 22
PEER_ID = 22


def text_message(
    text: str,
    *,
    message_id: int = 1,
    peer_id: int = PEER_ID,
    from_id: int | None = None,
) -> Message:
    return Message(
        id=message_id,
        date=1,
        peer_id=peer_id,
        from_id=from_id if from_id is not None else peer_id,
        text=text,
        out=0,
        conversation_message_id=message_id,
        version=0,
    )


def callback_event(
    payload: dict | str,
    *,
    event_id: str = "100",
    peer_id: int = PEER_ID,
    user_id: int | None = None,
) -> MessageEvent:
    raw = payload if isinstance(payload, dict) else {"p": payload}
    return MessageEvent(
        type="message_event",
        object=MessageEventObject(
            user_id=user_id if user_id is not None else peer_id,
            peer_id=peer_id,
            event_id=event_id,
            payload=raw,
        ),
        group_id=100,
    )


def keyboard_buttons(keyboard: str | None) -> list[tuple[str, dict]]:
    if not keyboard:
        return []
    data = json.loads(keyboard)
    buttons: list[tuple[str, dict]] = []
    for row in data.get("buttons", []):
        for button in row:
            action = button.get("action", {})
            buttons.append((action.get("label", ""), action.get("payload") or {}))
    return buttons


@pytest.fixture
def vk_harness() -> tuple[VkUpdateProcessor, RecordingVkSender, InMemoryUnitOfWorkFactory]:
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
    sender = RecordingVkSender()
    renderer = VkRenderer(
        sender=sender,
        resolver=CatalogMediaResolver(catalog, uow_factory, platform="vk"),
        policy=VkMediaPolicy(),
        catalog=catalog,
        uow_factory=uow_factory,
        media_cache=InMemoryVkMediaCache(),
        community_id="100",
        clock=lambda: NOW,
    )
    delivery = VkDeliveryService(
        uow_factory=uow_factory,
        renderer=renderer,
        catalog=catalog,
        clock=lambda: NOW,
    )
    processor = VkUpdateProcessor(service, renderer, uow_factory, delivery)
    return processor, sender, uow_factory
