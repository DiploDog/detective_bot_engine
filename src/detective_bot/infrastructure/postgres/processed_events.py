from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from detective_bot.application.models import PlayerContext
from detective_bot.infrastructure.postgres.models import ProcessedEventRow
from detective_bot.infrastructure.postgres.sessions import (
    get_or_create_player_context,
)


class PostgresProcessedEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def try_register(
        self,
        player_context: PlayerContext,
        external_event_id: str,
        *,
        processed_at: datetime,
    ) -> bool:
        player_id = await get_or_create_player_context(
            self._db,
            player_context,
            now=processed_at,
        )
        statement = (
            insert(ProcessedEventRow)
            .values(
                player_context_id=player_id,
                external_event_id=external_event_id,
                processed_at=processed_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_processed_event_identity"
            )
            .returning(ProcessedEventRow.id)
        )
        return (await self._db.execute(statement)).scalar_one_or_none() is not None
