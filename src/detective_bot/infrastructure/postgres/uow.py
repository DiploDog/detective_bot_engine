from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.infrastructure.postgres.interaction_log import (
    PostgresInteractionLogRepository,
)
from detective_bot.infrastructure.postgres.outbound import (
    PostgresOutboundDeliveryRepository,
)
from detective_bot.infrastructure.postgres.processed_events import (
    PostgresProcessedEventRepository,
)
from detective_bot.infrastructure.postgres.scheduled_actions import (
    PostgresScheduledActionRepository,
)
from detective_bot.infrastructure.postgres.sessions import (
    PostgresSessionRepository,
)


class PostgresUnitOfWork:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._db: AsyncSession | None = None

    async def __aenter__(self) -> PostgresUnitOfWork:
        self._db = self._session_factory()
        self.sessions = PostgresSessionRepository(self._db)
        self.scheduled_actions = PostgresScheduledActionRepository(self._db)
        self.processed_events = PostgresProcessedEventRepository(self._db)
        self.interaction_log = PostgresInteractionLogRepository(self._db)
        self.outbound_deliveries = PostgresOutboundDeliveryRepository(self._db)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._db is None:
            return
        if exc_type is not None or self._db.in_transaction():
            await self._db.rollback()
        await self._db.close()
        self._db = None

    async def commit(self) -> None:
        self._require_db()
        await self._db.commit()  # type: ignore[union-attr]

    async def rollback(self) -> None:
        self._require_db()
        await self._db.rollback()  # type: ignore[union-attr]

    def _require_db(self) -> None:
        if self._db is None:
            raise RuntimeError("unit of work is not active")


class PostgresUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(self._session_factory)
