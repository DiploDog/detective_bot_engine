from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from itertools import count

from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.adapters.telegram.delivery import TelegramDeliveryService
from detective_bot.adapters.telegram.handlers import TelegramUpdateProcessor
from detective_bot.adapters.telegram.media import CatalogMediaResolver
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.application.models import (
    ConfirmRestart,
    IncomingInteraction,
    Notice,
    OutboundDeliveryStatus,
    Platform,
    PlayerContext,
    SelectGame,
    SubmitGameInput,
)
from detective_bot.application.outbound import build_outbound_deliveries
from detective_bot.application.service import ApplicationService
from detective_bot.engine.model import TextInput
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres.models import (
    OutboundDeliveryRow,
    ScheduledActionRow,
)
from detective_bot.infrastructure.postgres.uow import PostgresUnitOfWorkFactory
from tests.fakes import InMemoryTelegramMediaCache, RecordingTelegramSender
from tests.integration.postgres.conftest import NOW, ROOT
from tests.unit.telegram.conftest import callback_update
from detective_bot.adapters.telegram.callback_data import (
    SelectGameCallback,
    pack_callback,
)


PLAYER = PlayerContext(Platform.TELEGRAM, "22", "22")


@dataclass
class MutableClock:
    now: object

    def __call__(self):
        return self.now


def make_stack(
    uow_factory: PostgresUnitOfWorkFactory,
    *,
    clock=None,
    sender: RecordingTelegramSender | None = None,
    first_id: int = 1,
):
    catalog = FileSystemGameCatalog(ROOT / "games")
    sequence = count(first_id)
    current_clock = clock or (lambda: NOW)
    service = ApplicationService(
        catalog=catalog,
        uow_factory=uow_factory,
        engine=GameEngine(),
        clock=current_clock,
        session_id_factory=lambda: f"session-{next(sequence)}",
    )
    sender = sender or RecordingTelegramSender()
    renderer = TelegramRenderer(
        sender=sender,
        resolver=CatalogMediaResolver(catalog, uow_factory),
        policy=TelegramMediaPolicy(),
        catalog=catalog,
        uow_factory=uow_factory,
        media_cache=InMemoryTelegramMediaCache(),
        bot_id="22",
        clock=current_clock,
    )
    delivery = TelegramDeliveryService(
        uow_factory=uow_factory,
        renderer=renderer,
        catalog=catalog,
        clock=current_clock,
    )
    processor = TelegramUpdateProcessor(service, renderer, uow_factory, delivery)
    return service, delivery, processor, sender


async def handle(service: ApplicationService, action, event_id: str):
    return await service.handle(
        IncomingInteraction(
            player_context=PLAYER,
            action=action,
            external_event_id=event_id,
        )
    )


async def reach_margo_articles(service: ApplicationService) -> None:
    await handle(service, SelectGame("killing_margo"), "margo-select")
    async with service._uow_factory() as uow:
        selected = await uow.sessions.get_selected(PLAYER)
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
    await handle(service, SubmitGameInput(TextInput(text="31,33")), "margo-q9")


async def test_concurrent_claim_has_no_overlap(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    service, delivery, _, _ = make_stack(uow_factory)
    await handle(service, SelectGame("lora_dein"), "seed-player")
    notices = tuple(Notice("n", f"msg-{index}") for index in range(8))
    async with uow_factory() as uow:
        await uow.outbound_deliveries.add(
            build_outbound_deliveries(
                PLAYER,
                notices,
                source_event_id="claim-batch",
                now=NOW,
            )
        )
        await uow.commit()

    async def claim() -> set[int]:
        async with uow_factory() as uow:
            claimed = await uow.outbound_deliveries.claim_due(
                "telegram",
                now=NOW,
                limit=8,
                lease_until=NOW + timedelta(seconds=30),
            )
            await uow.commit()
        return {item.delivery_id for item in claimed if item.delivery_id is not None}

    first, second = await asyncio.gather(claim(), claim())
    assert first.isdisjoint(second)
    assert first | second


async def test_expired_lease_is_recovered_and_delivered(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, delivery, _, sender = make_stack(uow_factory)
    await handle(service, SelectGame("lora_dein"), "lease-select")
    async with session_factory() as db:
        row = (
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.source_event_id == "lease-select"
                )
            )
        ).first()
        assert row is not None
        row.status = "claimed"
        row.claimed_at = NOW
        row.lease_until = NOW - timedelta(seconds=1)
        await db.commit()

    await delivery.tick()
    async with session_factory() as db:
        statuses = set(
            await db.scalars(
                select(OutboundDeliveryRow.status).where(
                    OutboundDeliveryRow.source_event_id == "lease-select"
                )
            )
        )
    assert statuses == {"delivered"}
    assert sender.calls


async def test_retry_then_success(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = MutableClock(NOW)
    sender = RecordingTelegramSender()
    sender.fail_always = RuntimeError("temporary")
    service, delivery, _, sender = make_stack(
        uow_factory,
        clock=clock,
        sender=sender,
    )
    await handle(service, SelectGame("lora_dein"), "retry-select")
    await delivery.deliver_source_event(PLAYER, "retry-select")
    async with session_factory() as db:
        pending = list(
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.source_event_id == "retry-select"
                )
            )
        )
    assert pending
    assert all(row.status == "pending" for row in pending)
    assert all(row.last_error_code == "send_failed" for row in pending)
    assert sender.calls == []

    sender.fail_always = None
    clock.now = NOW + timedelta(seconds=1)
    await delivery.deliver_source_event(PLAYER, "retry-select")
    assert sender.calls
    async with session_factory() as db:
        statuses = set(
            await db.scalars(
                select(OutboundDeliveryRow.status).where(
                    OutboundDeliveryRow.source_event_id == "retry-select"
                )
            )
        )
    assert statuses == {"delivered"}


async def test_retry_after_uses_telegram_delay(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sender = RecordingTelegramSender()
    sender.fail_always = TelegramRetryAfter(
        SendMessage(chat_id=22, text="x"),
        "flood",
        12,
    )
    service, delivery, _, _ = make_stack(uow_factory, sender=sender)
    await handle(service, SelectGame("lora_dein"), "retry-after")
    await delivery.deliver_source_event(PLAYER, "retry-after")
    async with session_factory() as db:
        row = (
            await db.scalars(
                select(OutboundDeliveryRow)
                .where(OutboundDeliveryRow.source_event_id == "retry-after")
                .order_by(OutboundDeliveryRow.sequence_no)
            )
        ).first()
    assert row is not None
    assert row.status == "pending"
    assert row.last_error_code == "telegram_retry_after"
    assert row.next_attempt_at == NOW + timedelta(seconds=12)


async def test_pending_immediate_output_survives_service_restart(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    service, _, _, _ = make_stack(uow_factory)
    await handle(service, SelectGame("lora_dein"), "survive-select")
    restarted = make_stack(uow_factory, first_id=99)
    _, delivery, _, sender = restarted
    await delivery.deliver_due()
    assert sender.calls
    assert any(call.method == "text" for call in sender.calls)


async def test_outbound_order_is_preserved(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    service, delivery, _, sender = make_stack(uow_factory)
    await handle(service, SelectGame("killing_margo"), "order-select")
    async with service._uow_factory() as uow:
        selected = await uow.sessions.get_selected(PLAYER)
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
    result = await handle(
        service,
        SubmitGameInput(TextInput(text="31,33")),
        "order-q9",
    )
    await delivery.deliver_source_event(PLAYER, "order-q9")
    sent_texts = [call.text for call in sender.calls if call.text]
    expected = [
        action.text
        for action in result.outputs[0].actions  # type: ignore[attr-defined]
        if getattr(action, "text", None)
    ]
    assert sent_texts[: len(expected)] == expected


async def test_margo_reveal_arrives_at_plus_300(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = MutableClock(NOW)
    service, delivery, _, sender = make_stack(uow_factory, clock=clock)
    await reach_margo_articles(service)
    sender.calls.clear()

    clock.now = NOW + timedelta(seconds=299)
    await delivery.tick()
    assert not any("чуть не забыл" in (call.text or "") for call in sender.calls)

    clock.now = NOW + timedelta(seconds=300)
    await delivery.tick()
    assert any("чуть не забыл" in (call.text or "") for call in sender.calls)
    async with session_factory() as db:
        scheduled = (await db.scalars(select(ScheduledActionRow))).one()
        assert scheduled.status == "delivered"
        outbound = list(
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.source_event_id.like("schedule:%")
                )
            )
        )
        assert outbound
        assert all(row.status == "delivered" for row in outbound)


async def test_early_killer_cancels_reveal(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = MutableClock(NOW)
    service, delivery, _, sender = make_stack(uow_factory, clock=clock)
    await reach_margo_articles(service)
    await handle(
        service,
        SubmitGameInput(TextInput(text="готов назвать убийцу")),
        "go-killer",
    )
    sender.calls.clear()
    clock.now = NOW + timedelta(seconds=300)
    await delivery.tick()
    assert not any("чуть не забыл" in (call.text or "") for call in sender.calls)
    async with session_factory() as db:
        scheduled = (await db.scalars(select(ScheduledActionRow))).one()
        assert scheduled.status == "cancelled"


async def test_restart_cancels_old_reveal(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = MutableClock(NOW)
    service, delivery, _, sender = make_stack(uow_factory, clock=clock)
    await reach_margo_articles(service)
    await handle(service, ConfirmRestart("session-1"), "restart-margo")
    sender.calls.clear()
    clock.now = NOW + timedelta(seconds=300)
    await delivery.tick()
    assert not any("чуть не забыл" in (call.text or "") for call in sender.calls)
    async with session_factory() as db:
        old = (
            await db.scalars(
                select(ScheduledActionRow).where(
                    ScheduledActionRow.session_id == "session-1"
                )
            )
        ).one()
        assert old.status == "cancelled"


async def test_processor_does_not_double_send_with_pump(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    _, delivery, processor, sender = make_stack(uow_factory)
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=1)
    )
    first = len(sender.calls)
    assert first > 0
    await delivery.tick()
    assert len(sender.calls) == first
