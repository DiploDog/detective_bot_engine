from __future__ import annotations

import asyncio

from detective_bot.application.models import Platform, PlayerContext
from detective_bot.infrastructure.postgres.uow import (
    PostgresUnitOfWorkFactory,
)
from tests.integration.postgres.conftest import NOW


PLAYER = PlayerContext(Platform.TELEGRAM, "event-user", "event-chat")


async def test_event_registration_is_deduplicated_sequentially(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    async with uow_factory() as first:
        assert await first.processed_events.try_register(
            PLAYER,
            "event-1",
            processed_at=NOW,
        )
        await first.commit()

    async with uow_factory() as second:
        assert not await second.processed_events.try_register(
            PLAYER,
            "event-1",
            processed_at=NOW,
        )


async def test_event_registration_is_atomic_across_transactions(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    async with uow_factory() as seed:
        await seed.sessions.set_selected(PLAYER, None, updated_at=NOW)
        await seed.commit()

    async with uow_factory() as first, uow_factory() as second:
        assert await first.processed_events.try_register(
            PLAYER,
            "event-race",
            processed_at=NOW,
        )
        competing = asyncio.create_task(
            second.processed_events.try_register(
                PLAYER,
                "event-race",
                processed_at=NOW,
            )
        )
        await asyncio.sleep(0.1)
        assert not competing.done()
        await first.commit()
        assert not await competing


async def test_rolled_back_event_registration_can_be_retried(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    async with uow_factory() as rolled_back:
        assert await rolled_back.processed_events.try_register(
            PLAYER,
            "event-retry",
            processed_at=NOW,
        )

    async with uow_factory() as retry:
        assert await retry.processed_events.try_register(
            PLAYER,
            "event-retry",
            processed_at=NOW,
        )
        await retry.commit()
