from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from detective_bot.application.models import (
    ApplicationSession,
    OutboundDelivery,
    PlayerContext,
    SessionInteractionRecord,
    StoredScheduledAction,
)
from detective_bot.engine.model import GamePackage, ScheduledActionRequest


class SessionConflict(RuntimeError):
    pass


class LoadedPackage(Protocol):
    @property
    def package(self) -> GamePackage: ...


class GameCatalogPort(Protocol):
    def list_games(self) -> tuple[str, ...]: ...

    def get(self, game_id: str, version: str) -> LoadedPackage: ...

    def get_latest(self, game_id: str) -> LoadedPackage: ...


class SessionRepository(Protocol):
    async def get(
        self,
        session_id: str,
        *,
        lock_owner: bool = False,
    ) -> ApplicationSession | None: ...

    async def find_resumable(
        self,
        player_context: PlayerContext,
        game_id: str,
    ) -> ApplicationSession | None: ...

    async def list_resumable(
        self,
        player_context: PlayerContext,
    ) -> tuple[ApplicationSession, ...]: ...

    async def create(self, session: ApplicationSession) -> None: ...

    async def save(
        self,
        session: ApplicationSession,
        *,
        expected_revision: int,
    ) -> None: ...

    async def mark_superseded(
        self,
        session_id: str,
        *,
        superseded_at: datetime,
        expected_revision: int,
    ) -> ApplicationSession: ...

    async def get_selected(
        self,
        player_context: PlayerContext,
    ) -> ApplicationSession | None: ...

    async def set_selected(
        self,
        player_context: PlayerContext,
        session_id: str | None,
        *,
        updated_at: datetime,
    ) -> None: ...


class ScheduledActionRepository(Protocol):
    async def add(
        self,
        session_id: str,
        origin_revision: int,
        requests: tuple[ScheduledActionRequest, ...],
        *,
        created_at: datetime,
    ) -> None: ...

    async def cancel_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None: ...

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[StoredScheduledAction, ...]: ...

    async def mark_delivered(
        self,
        action_id: int,
        *,
        delivered_at: datetime,
    ) -> None: ...

    async def reschedule_after_failure(
        self,
        action_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None: ...

    async def release_expired_claims(self, *, now: datetime) -> int: ...

    async def mark_cancelled(
        self,
        action_id: int,
        *,
        cancelled_at: datetime,
    ) -> None: ...


class ProcessedEventRepository(Protocol):
    async def try_register(
        self,
        player_context: PlayerContext,
        external_event_id: str,
        *,
        processed_at: datetime,
    ) -> bool: ...


class InteractionLogRepository(Protocol):
    async def add(self, record: SessionInteractionRecord) -> None: ...


class OutboundDeliveryRepository(Protocol):
    async def add(self, deliveries: tuple[OutboundDelivery, ...]) -> None: ...

    async def cancel_pending_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None: ...

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]: ...

    async def claim_source_event(
        self,
        player_context: PlayerContext,
        source_event_id: str,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]: ...

    async def mark_delivered(
        self,
        delivery_id: int,
        *,
        delivered_at: datetime,
    ) -> None: ...

    async def reschedule_after_failure(
        self,
        delivery_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None: ...

    async def mark_dead(
        self,
        delivery_id: int,
        *,
        error_code: str,
    ) -> None: ...

    async def release_expired_claims(self, *, now: datetime) -> int: ...


class ApplicationUnitOfWork(Protocol):
    sessions: SessionRepository
    scheduled_actions: ScheduledActionRepository
    processed_events: ProcessedEventRepository
    interaction_log: InteractionLogRepository
    outbound_deliveries: OutboundDeliveryRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> ApplicationUnitOfWork: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class SessionIdFactory(Protocol):
    def __call__(self) -> str: ...
