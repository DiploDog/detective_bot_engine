from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.application.models import (
    ApplicationSession,
    Platform,
    PlayerContext,
    ScheduledActionStatus,
)
from detective_bot.engine.model import ScheduledActionRequest
from detective_bot.infrastructure.postgres.models import ScheduledActionRow
from detective_bot.infrastructure.postgres.uow import (
    PostgresUnitOfWorkFactory,
)
from tests.integration.postgres.conftest import NOW


PLAYER = PlayerContext(Platform.TELEGRAM, "schedule-user", "schedule-chat")


def request(key: str, *, due_offset: int = 0) -> ScheduledActionRequest:
    return ScheduledActionRequest(
        template_id="reveal_articles",
        due_at=NOW + timedelta(seconds=due_offset),
        idempotency_key=key,
    )


async def seed_session(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    async with uow_factory() as uow:
        await uow.sessions.create(
            session_builder(
                session_id="margo-session",
                player=PLAYER,
                game_id="killing_margo",
                current_scene="margo_articles",
            )
        )
        await uow.commit()


async def test_schedule_idempotency_includes_origin_revision(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
    session_builder: Callable[..., ApplicationSession],
) -> None:
    await seed_session(uow_factory, session_builder)
    scheduled = (request("same-key"),)
    async with uow_factory() as uow:
        await uow.scheduled_actions.add(
            "margo-session",
            5,
            scheduled,
            created_at=NOW,
        )
        await uow.scheduled_actions.add(
            "margo-session",
            5,
            scheduled,
            created_at=NOW,
        )
        await uow.scheduled_actions.add(
            "margo-session",
            6,
            scheduled,
            created_at=NOW,
        )
        await uow.commit()

    async with session_factory() as db:
        count = await db.scalar(
            select(func.count()).select_from(ScheduledActionRow)
        )
        assert count == 2


async def test_cancel_marks_pending_and_claimed_actions(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
    session_builder: Callable[..., ApplicationSession],
) -> None:
    await seed_session(uow_factory, session_builder)
    async with uow_factory() as uow:
        await uow.scheduled_actions.add(
            "margo-session",
            5,
            (request("first"), request("second")),
            created_at=NOW,
        )
        await uow.commit()

    async with uow_factory() as uow:
        claimed = await uow.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW,
            limit=1,
            lease_until=NOW + timedelta(minutes=1),
        )
        assert len(claimed) == 1
        await uow.scheduled_actions.cancel_for_session(
            "margo-session",
            cancelled_at=NOW,
        )
        await uow.commit()

    async with session_factory() as db:
        statuses = (
            await db.scalars(
                select(ScheduledActionRow.status).order_by(ScheduledActionRow.id)
            )
        ).all()
        assert statuses == ["cancelled", "cancelled"]


async def test_concurrent_claims_use_skip_locked_without_overlap(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    await seed_session(uow_factory, session_builder)
    async with uow_factory() as seed:
        await seed.scheduled_actions.add(
            "margo-session",
            5,
            tuple(request(f"key-{index}") for index in range(4)),
            created_at=NOW,
        )
        await seed.commit()

    async with uow_factory() as first, uow_factory() as second:
        first_claim = await first.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW,
            limit=2,
            lease_until=NOW + timedelta(minutes=1),
        )
        second_claim = await second.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW,
            limit=4,
            lease_until=NOW + timedelta(minutes=1),
        )
        first_ids = {item.action_id for item in first_claim}
        second_ids = {item.action_id for item in second_claim}
        assert len(first_ids) == 2
        assert len(second_ids) == 2
        assert first_ids.isdisjoint(second_ids)
        await first.commit()
        await second.commit()


async def test_expired_lease_is_released_and_reclaimed(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    await seed_session(uow_factory, session_builder)
    async with uow_factory() as seed:
        await seed.scheduled_actions.add(
            "margo-session",
            5,
            (request("lease"),),
            created_at=NOW,
        )
        await seed.commit()

    async with uow_factory() as first:
        claimed = await first.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW,
            limit=1,
            lease_until=NOW + timedelta(seconds=30),
        )
        assert claimed[0].status is ScheduledActionStatus.CLAIMED
        assert claimed[0].attempts == 1
        await first.commit()

    later = NOW + timedelta(seconds=31)
    async with uow_factory() as recovery:
        assert await recovery.scheduled_actions.release_expired_claims(
            now=later
        ) == 1
        await recovery.commit()

    async with uow_factory() as second:
        reclaimed = await second.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=later,
            limit=1,
            lease_until=later + timedelta(seconds=30),
        )
        assert reclaimed[0].attempts == 2
        await second.scheduled_actions.mark_delivered(
            reclaimed[0].action_id,
            delivered_at=later,
        )
        await second.commit()


async def test_failed_claim_respects_next_attempt_time(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    await seed_session(uow_factory, session_builder)
    async with uow_factory() as seed:
        await seed.scheduled_actions.add(
            "margo-session",
            5,
            (request("retry"),),
            created_at=NOW,
        )
        await seed.commit()

    retry_at = NOW + timedelta(minutes=2)
    async with uow_factory() as first:
        claimed = await first.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW,
            limit=1,
            lease_until=NOW + timedelta(seconds=30),
        )
        await first.scheduled_actions.reschedule_after_failure(
            claimed[0].action_id,
            next_attempt_at=retry_at,
            error_code="temporary",
        )
        await first.commit()

    async with uow_factory() as too_early:
        assert await too_early.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=NOW + timedelta(minutes=1),
            limit=1,
            lease_until=retry_at,
        ) == ()

    async with uow_factory() as retry:
        claimed_again = await retry.scheduled_actions.claim_due(
            Platform.TELEGRAM.value,
            now=retry_at,
            limit=1,
            lease_until=retry_at + timedelta(seconds=30),
        )
        assert claimed_again[0].attempts == 2
        assert claimed_again[0].last_error_code == "temporary"
        await retry.commit()
