from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from itertools import count

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vkbottle import VKAPIError

from detective_bot.adapters.media import CatalogMediaResolver
from detective_bot.adapters.telegram.callback_data import SelectGameCallback
from detective_bot.adapters.vk.callback_data import pack_payload
from detective_bot.adapters.vk.delivery import VkDeliveryService
from detective_bot.adapters.vk.handlers import VkUpdateProcessor
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.application.models import (
    ConfirmRestart,
    IncomingInteraction,
    Platform,
    PlayerContext,
    SelectGame,
    SubmitGameInput,
)
from detective_bot.application.service import ApplicationService
from detective_bot.engine.model import TextInput
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres.models import (
    OutboundDeliveryRow,
    ScheduledActionRow,
)
from detective_bot.infrastructure.postgres.uow import PostgresUnitOfWorkFactory
from tests.fakes import InMemoryVkMediaCache, RecordingVkSender
from tests.integration.postgres.conftest import NOW, ROOT
from tests.unit.vk.conftest import callback_event


PLAYER = PlayerContext(Platform.VK, "22", "22")
TELEGRAM_PLAYER = PlayerContext(Platform.TELEGRAM, "22", "22")


@dataclass
class MutableClock:
    now: object

    def __call__(self):
        return self.now


def make_stack(
    uow_factory: PostgresUnitOfWorkFactory,
    *,
    clock=None,
    sender: RecordingVkSender | None = None,
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
    sender = sender or RecordingVkSender()
    renderer = VkRenderer(
        sender=sender,
        resolver=CatalogMediaResolver(catalog, uow_factory),
        policy=VkMediaPolicy(),
        catalog=catalog,
        uow_factory=uow_factory,
        media_cache=InMemoryVkMediaCache(),
        community_id="100",
        clock=current_clock,
    )
    delivery = VkDeliveryService(
        uow_factory=uow_factory,
        renderer=renderer,
        catalog=catalog,
        clock=current_clock,
    )
    processor = VkUpdateProcessor(service, renderer, uow_factory, delivery)
    return service, delivery, processor, sender


async def handle(service: ApplicationService, action, event_id: str, player=PLAYER):
    return await service.handle(
        IncomingInteraction(
            player_context=player,
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


async def test_vk_worker_does_not_claim_telegram_destinations(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    service, vk_delivery, _, sender = make_stack(uow_factory)
    await handle(
        service,
        SelectGame("lora_dein"),
        "tg-select",
        player=TELEGRAM_PLAYER,
    )
    await vk_delivery.deliver_due()
    assert sender.calls == []
    async with uow_factory() as uow:
        claimed = await uow.outbound_deliveries.claim_due(
            "telegram",
            now=NOW,
            limit=20,
            lease_until=NOW + timedelta(seconds=30),
        )
        await uow.rollback()
    assert claimed


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
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("lora_dein")), event_id="1")
    )
    first = len(sender.calls)
    assert first > 0
    await delivery.tick()
    assert len(sender.calls) == first


async def test_vk_flood_uses_retry_after(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sender = RecordingVkSender()
    sender.fail_always = VKAPIError[6](error_msg="too many requests per second")
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
    assert row.last_error_code == "vk_retry_after"
    assert row.next_attempt_at == NOW + timedelta(seconds=1)
