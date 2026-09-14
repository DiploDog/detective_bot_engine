from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import TracebackType

from detective_bot.application.models import (
    ApplicationSession,
    ApplicationSessionStatus,
    OutboundDelivery,
    OutboundDeliveryStatus,
    PlayerContext,
    SessionInteractionRecord,
    StoredScheduledAction,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.engine.model import ScheduledActionRequest


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, ApplicationSession] = {}
        self.selected: dict[PlayerContext, str] = {}
        self.created_ids: list[str] = []
        self.saved_ids: list[str] = []

    async def get(
        self,
        session_id: str,
        *,
        lock_owner: bool = False,
    ) -> ApplicationSession | None:
        del lock_owner
        return self.sessions.get(session_id)

    async def find_resumable(
        self,
        player_context: PlayerContext,
        game_id: str,
    ) -> ApplicationSession | None:
        candidates = [
            session
            for session in self.sessions.values()
            if session.player_context == player_context
            and session.game_id == game_id
            and session.status is ApplicationSessionStatus.IN_PROGRESS
        ]
        return max(candidates, key=lambda item: item.created_at, default=None)

    async def list_resumable(
        self,
        player_context: PlayerContext,
    ) -> tuple[ApplicationSession, ...]:
        return tuple(
            sorted(
                (
                    session
                    for session in self.sessions.values()
                    if session.player_context == player_context
                    and session.status is ApplicationSessionStatus.IN_PROGRESS
                ),
                key=lambda item: (item.game_id, item.created_at),
            )
        )

    async def create(self, session: ApplicationSession) -> None:
        if session.session_id in self.sessions:
            raise SessionConflict(
                f"session already exists: {session.session_id}"
            )
        self.sessions[session.session_id] = session
        self.created_ids.append(session.session_id)

    async def save(
        self,
        session: ApplicationSession,
        *,
        expected_revision: int,
    ) -> None:
        current = self.sessions.get(session.session_id)
        if current is None:
            raise SessionConflict(f"session does not exist: {session.session_id}")
        if current.engine_snapshot.revision != expected_revision:
            raise SessionConflict(
                f"expected revision {expected_revision}, "
                f"found {current.engine_snapshot.revision}"
            )
        self.sessions[session.session_id] = session
        self.saved_ids.append(session.session_id)

    async def mark_superseded(
        self,
        session_id: str,
        *,
        superseded_at: datetime,
        expected_revision: int,
    ) -> ApplicationSession:
        current = self.sessions.get(session_id)
        if current is None:
            raise SessionConflict(f"session does not exist: {session_id}")
        if current.engine_snapshot.revision != expected_revision:
            raise SessionConflict(
                f"expected revision {expected_revision}, "
                f"found {current.engine_snapshot.revision}"
            )
        superseded = replace(
            current,
            updated_at=superseded_at,
            superseded_at=superseded_at,
        )
        self.sessions[session_id] = superseded
        return superseded

    async def get_selected(
        self,
        player_context: PlayerContext,
    ) -> ApplicationSession | None:
        session_id = self.selected.get(player_context)
        return self.sessions.get(session_id) if session_id is not None else None

    async def set_selected(
        self,
        player_context: PlayerContext,
        session_id: str | None,
        *,
        updated_at: datetime,
    ) -> None:
        del updated_at
        if session_id is None:
            self.selected.pop(player_context, None)
            return
        session = self.sessions.get(session_id)
        if session is None or session.player_context != player_context:
            raise SessionConflict("selected session is missing or belongs to another player")
        self.selected[player_context] = session_id


class InMemoryScheduledActionRepository:
    def __init__(self) -> None:
        self.requests: dict[str, list[ScheduledActionRequest]] = {}
        self.origins: dict[str, list[int]] = {}
        self.cancelled_session_ids: list[str] = []

    async def add(
        self,
        session_id: str,
        origin_revision: int,
        requests: tuple[ScheduledActionRequest, ...],
        *,
        created_at: datetime,
    ) -> None:
        del created_at
        stored = self.requests.setdefault(session_id, [])
        origins = self.origins.setdefault(session_id, [])
        existing = {
            (origin, request.idempotency_key)
            for origin, request in zip(origins, stored, strict=True)
        }
        for request in requests:
            key = (origin_revision, request.idempotency_key)
            if key not in existing:
                stored.append(request)
                origins.append(origin_revision)
                existing.add(key)

    async def cancel_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None:
        del cancelled_at
        self.cancelled_session_ids.append(session_id)

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[StoredScheduledAction, ...]:
        del platform, now, limit, lease_until
        return ()

    async def mark_delivered(
        self,
        action_id: int,
        *,
        delivered_at: datetime,
    ) -> None:
        del action_id, delivered_at

    async def reschedule_after_failure(
        self,
        action_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None:
        del action_id, next_attempt_at, error_code

    async def release_expired_claims(self, *, now: datetime) -> int:
        del now
        return 0

    async def mark_cancelled(
        self,
        action_id: int,
        *,
        cancelled_at: datetime,
    ) -> None:
        del cancelled_at
        self.cancelled_session_ids.append(str(action_id))


class InMemoryProcessedEventRepository:
    def __init__(self) -> None:
        self.processed: set[tuple[PlayerContext, str]] = set()

    async def try_register(
        self,
        player_context: PlayerContext,
        external_event_id: str,
        *,
        processed_at: datetime,
    ) -> bool:
        del processed_at
        key = (player_context, external_event_id)
        if key in self.processed:
            return False
        self.processed.add(key)
        return True


class InMemoryInteractionLogRepository:
    def __init__(self) -> None:
        self.records: list[SessionInteractionRecord] = []

    async def add(self, record: SessionInteractionRecord) -> None:
        self.records.append(record)


class InMemoryOutboundDeliveryRepository:
    def __init__(self) -> None:
        self.deliveries: list[OutboundDelivery] = []
        self._next_id = 1

    async def add(self, deliveries: tuple[OutboundDelivery, ...]) -> None:
        for item in deliveries:
            if item.delivery_id is None:
                item = replace(item, delivery_id=self._next_id)
                self._next_id += 1
            self.deliveries.append(item)

    async def cancel_pending_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None:
        del cancelled_at
        self.deliveries = [
            replace(item, status=OutboundDeliveryStatus.CANCELLED)
            if (
                item.session_id == session_id
                and item.status is OutboundDeliveryStatus.PENDING
            )
            else item
            for item in self.deliveries
        ]

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        due = [
            item
            for item in self.deliveries
            if item.player_context.platform.value == platform
            and _outbound_is_due(item, now)
        ]
        due.sort(key=lambda item: (item.due_at, item.sequence_no, item.delivery_id or 0))
        return self._claim(due[:limit], now=now, lease_until=lease_until)

    async def claim_source_event(
        self,
        player_context: PlayerContext,
        source_event_id: str,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        due = [
            item
            for item in self.deliveries
            if item.player_context == player_context
            and item.source_event_id == source_event_id
            and _outbound_is_due(item, now)
        ]
        due.sort(key=lambda item: (item.sequence_no, item.delivery_id or 0))
        return self._claim(due, now=now, lease_until=lease_until)

    async def mark_delivered(
        self,
        delivery_id: int,
        *,
        delivered_at: datetime,
    ) -> None:
        self._require_claimed(delivery_id)
        self._replace(
            delivery_id,
            status=OutboundDeliveryStatus.DELIVERED,
            delivered_at=delivered_at,
            claimed_at=None,
            lease_until=None,
        )

    async def reschedule_after_failure(
        self,
        delivery_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None:
        self._require_claimed(delivery_id)
        self._replace(
            delivery_id,
            status=OutboundDeliveryStatus.PENDING,
            next_attempt_at=next_attempt_at,
            last_error_code=error_code,
            claimed_at=None,
            lease_until=None,
        )

    async def mark_dead(
        self,
        delivery_id: int,
        *,
        error_code: str,
    ) -> None:
        self._require_claimed(delivery_id)
        self._replace(
            delivery_id,
            status=OutboundDeliveryStatus.DEAD,
            last_error_code=error_code,
            claimed_at=None,
            lease_until=None,
        )

    async def release_expired_claims(self, *, now: datetime) -> int:
        released = 0
        updated: list[OutboundDelivery] = []
        for item in self.deliveries:
            if (
                item.status is OutboundDeliveryStatus.CLAIMED
                and item.lease_until is not None
                and item.lease_until <= now
            ):
                updated.append(
                    replace(
                        item,
                        status=OutboundDeliveryStatus.PENDING,
                        claimed_at=None,
                        lease_until=None,
                    )
                )
                released += 1
            else:
                updated.append(item)
        self.deliveries = updated
        return released

    def _claim(
        self,
        items: list[OutboundDelivery],
        *,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        claimed: list[OutboundDelivery] = []
        for item in items:
            updated = replace(
                item,
                status=OutboundDeliveryStatus.CLAIMED,
                claimed_at=now,
                lease_until=lease_until,
                attempts=item.attempts + 1,
            )
            self.deliveries = [
                updated if current.delivery_id == item.delivery_id else current
                for current in self.deliveries
            ]
            claimed.append(updated)
        return tuple(claimed)

    def _replace(self, delivery_id: int | None, **changes) -> None:
        self.deliveries = [
            replace(item, **changes) if item.delivery_id == delivery_id else item
            for item in self.deliveries
        ]

    def _require_claimed(self, delivery_id: int) -> OutboundDelivery:
        for item in self.deliveries:
            if item.delivery_id == delivery_id:
                if item.status is not OutboundDeliveryStatus.CLAIMED:
                    raise SessionConflict(
                        f"outbound delivery is not claimed: {delivery_id}"
                    )
                return item
        raise SessionConflict(f"outbound delivery is not claimed: {delivery_id}")


def _outbound_is_due(item: OutboundDelivery, now: datetime) -> bool:
    if item.status is not OutboundDeliveryStatus.PENDING:
        return False
    if item.due_at > now:
        return False
    return item.next_attempt_at is None or item.next_attempt_at <= now


class InMemoryUnitOfWork:
    def __init__(
        self,
        sessions: InMemorySessionRepository,
        scheduled_actions: InMemoryScheduledActionRepository,
        processed_events: InMemoryProcessedEventRepository,
        interaction_log: InMemoryInteractionLogRepository,
        outbound_deliveries: InMemoryOutboundDeliveryRepository,
    ) -> None:
        self.sessions = sessions
        self.scheduled_actions = scheduled_actions
        self.processed_events = processed_events
        self.interaction_log = interaction_log
        self.outbound_deliveries = outbound_deliveries
        self._snapshot: tuple | None = None
        self._committed = False

    async def __aenter__(self) -> InMemoryUnitOfWork:
        self._snapshot = (
            dict(self.sessions.sessions),
            dict(self.sessions.selected),
            list(self.sessions.created_ids),
            list(self.sessions.saved_ids),
            {
                session_id: list(requests)
                for session_id, requests in self.scheduled_actions.requests.items()
            },
            {
                session_id: list(origins)
                for session_id, origins in self.scheduled_actions.origins.items()
            },
            list(self.scheduled_actions.cancelled_session_ids),
            set(self.processed_events.processed),
            list(self.interaction_log.records),
            list(self.outbound_deliveries.deliveries),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        if self._snapshot is None:
            return
        targets = (
            self.sessions.sessions,
            self.sessions.selected,
            self.sessions.created_ids,
            self.sessions.saved_ids,
            self.scheduled_actions.requests,
            self.scheduled_actions.origins,
            self.scheduled_actions.cancelled_session_ids,
            self.processed_events.processed,
            self.interaction_log.records,
            self.outbound_deliveries.deliveries,
        )
        for target, saved in zip(targets, self._snapshot, strict=True):
            target.clear()
            if isinstance(target, dict):
                target.update(saved)
            elif isinstance(target, set):
                target.update(saved)
            else:
                target.extend(saved)
        self._committed = False


class InMemoryUnitOfWorkFactory:
    def __init__(self) -> None:
        self.sessions = InMemorySessionRepository()
        self.scheduled_actions = InMemoryScheduledActionRepository()
        self.processed_events = InMemoryProcessedEventRepository()
        self.interaction_log = InMemoryInteractionLogRepository()
        self.outbound_deliveries = InMemoryOutboundDeliveryRepository()

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(
            self.sessions,
            self.scheduled_actions,
            self.processed_events,
            self.interaction_log,
            self.outbound_deliveries,
        )
