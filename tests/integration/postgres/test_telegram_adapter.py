from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import count
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.adapters.telegram.callback_data import (
    SelectGameCallback,
    pack_callback,
)
from detective_bot.adapters.telegram.delivery import TelegramDeliveryService
from detective_bot.adapters.telegram.handlers import TelegramUpdateProcessor
from detective_bot.adapters.telegram.media import CatalogMediaResolver
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.application.models import ApplicationSessionStatus
from detective_bot.application.service import ApplicationService
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres.models import ScheduledActionRow
from detective_bot.infrastructure.postgres.uow import PostgresUnitOfWorkFactory
from tests.fakes import InMemoryTelegramMediaCache, RecordingTelegramSender
from tests.integration.postgres.conftest import NOW, ROOT
from tests.unit.telegram.conftest import callback_update, text_update


def make_processor(
    uow_factory: PostgresUnitOfWorkFactory,
) -> tuple[TelegramUpdateProcessor, RecordingTelegramSender]:
    catalog = FileSystemGameCatalog(ROOT / "games")
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
        policy=TelegramMediaPolicy(),
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
    return TelegramUpdateProcessor(service, renderer, uow_factory, delivery), sender


async def test_lora_complete_flow_persists_through_telegram_adapter(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    processor, sender = make_processor(uow_factory)
    await processor.process_update(text_update("/start", update_id=1))
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=2)
    )
    await processor.process_update(text_update("1,3", update_id=3))
    await processor.process_update(text_update("1,2", update_id=4))
    await processor.process_update(text_update("6", update_id=5))

    async with uow_factory() as uow:
        completed = await uow.sessions.get("session-1")
        assert completed is not None
        assert completed.status is ApplicationSessionStatus.COMPLETED
        assert completed.completed_at == NOW
        assert completed.engine_snapshot.current_scene == "lora_scene3"
    assert any("признанием" in (call.text or "") for call in sender.calls)


async def test_margo_q9_persists_audio_and_scheduled_row(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    processor, sender = make_processor(uow_factory)
    await processor.process_update(
        callback_update(
            pack_callback(SelectGameCallback("killing_margo")),
            update_id=1,
        )
    )
    async with uow_factory() as uow:
        selected = await uow.sessions.get("session-1")
        assert selected is not None
        await uow.sessions.save(
            replace(
                selected,
                engine_snapshot=selected.engine_snapshot.model_copy(
                    update={"current_scene": "margo_q9", "revision": 20}
                ),
            ),
            expected_revision=1,
        )
        await uow.commit()

    sender.calls.clear()
    await processor.process_update(text_update("31,33", update_id=2))

    assert any("ты прав" in (call.text or "") for call in sender.calls)
    audio = next(call for call in sender.calls if call.method == "audio")
    assert audio.path == (
        Path(ROOT) / "games/killing_margo/1.0.0/assets/phone_recording.mp3"
    )

    async with uow_factory() as uow:
        persisted = await uow.sessions.get("session-1")
        assert persisted is not None
        assert persisted.engine_snapshot.current_scene == "margo_articles"
        assert persisted.engine_snapshot.revision == 21
    async with session_factory() as db:
        scheduled = (await db.scalars(select(ScheduledActionRow))).one()
        assert scheduled.template_id == "reveal_articles"
        assert scheduled.due_at == NOW + timedelta(seconds=300)
        assert scheduled.status == "pending"
