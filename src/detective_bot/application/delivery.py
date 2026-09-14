from __future__ import annotations

from datetime import datetime, timedelta

from detective_bot.application.models import (
    ApplicationSession,
    GameActions,
    OutboundDelivery,
)
from detective_bot.application.outbound import build_outbound_deliveries
from detective_bot.application.ports import (
    Clock,
    GameCatalogPort,
    UnitOfWorkFactory,
)
from detective_bot.engine.model import ScheduledActionGuard, SessionStatus


OUTBOUND_MAX_ATTEMPTS = 5
OUTBOUND_LEASE_SECONDS = 30
OUTBOUND_BASE_BACKOFF_SECONDS = 1
OUTBOUND_MAX_BACKOFF_SECONDS = 60
SCHEDULE_CLAIM_LIMIT = 20
OUTBOUND_CLAIM_LIMIT = 20


def backoff_seconds(attempts: int) -> int:
    exponent = max(0, attempts - 1)
    return min(
        OUTBOUND_MAX_BACKOFF_SECONDS,
        OUTBOUND_BASE_BACKOFF_SECONDS * (2**exponent),
    )


def next_attempt_at(
    now: datetime,
    *,
    attempts: int,
    retry_after: float | None = None,
) -> datetime:
    delay = retry_after if retry_after is not None else backoff_seconds(attempts)
    return now + timedelta(seconds=delay)


def scheduled_guard_allows(
    guard: ScheduledActionGuard | None,
    session: ApplicationSession,
) -> bool:
    if session.superseded_at is not None:
        return False
    if guard is None:
        return True
    if (
        guard.session_status is not None
        and session.engine_snapshot.status is not SessionStatus(guard.session_status)
    ):
        return False
    if (
        guard.current_scene is not None
        and session.engine_snapshot.current_scene != guard.current_scene
    ):
        return False
    return True


class ScheduledActionMaterializer:
    def __init__(
        self,
        *,
        catalog: GameCatalogPort,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        lease_seconds: int = OUTBOUND_LEASE_SECONDS,
        limit: int = SCHEDULE_CLAIM_LIMIT,
    ) -> None:
        self._catalog = catalog
        self._uow_factory = uow_factory
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._limit = limit

    async def materialize_due(self, platform: str) -> int:
        now = self._clock()
        materialized = 0
        async with self._uow_factory() as uow:
            await uow.scheduled_actions.release_expired_claims(now=now)
            claimed = await uow.scheduled_actions.claim_due(
                platform,
                now=now,
                limit=self._limit,
                lease_until=now + timedelta(seconds=self._lease_seconds),
            )
            for action in claimed:
                session = await uow.sessions.get(action.session_id)
                if session is None:
                    await uow.scheduled_actions.mark_cancelled(
                        action.action_id,
                        cancelled_at=now,
                    )
                    continue
                try:
                    package = self._catalog.get(
                        session.game_id,
                        session.game_version,
                    ).package
                    template = package.definition.scheduled_actions[action.template_id]
                except (KeyError, ValueError):
                    await uow.scheduled_actions.mark_cancelled(
                        action.action_id,
                        cancelled_at=now,
                    )
                    continue
                if not scheduled_guard_allows(template.guard, session):
                    await uow.scheduled_actions.mark_cancelled(
                        action.action_id,
                        cancelled_at=now,
                    )
                    continue
                await uow.outbound_deliveries.add(
                    build_outbound_deliveries(
                        action.player_context,
                        (
                            GameActions(
                                session_id=action.session_id,
                                actions=template.actions,
                            ),
                        ),
                        source_event_id=f"schedule:{action.action_id}",
                        now=now,
                    )
                )
                await uow.scheduled_actions.mark_delivered(
                    action.action_id,
                    delivered_at=now,
                )
                materialized += 1
            await uow.commit()
        return materialized


def require_delivery_id(delivery: OutboundDelivery) -> int:
    if delivery.delivery_id is None:
        raise RuntimeError("outbound delivery is missing persistence id")
    return delivery.delivery_id
