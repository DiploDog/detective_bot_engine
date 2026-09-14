from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from detective_bot.application.models import SessionInteractionRecord
from detective_bot.infrastructure.postgres.models import SessionInteractionRow


class PostgresInteractionLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, record: SessionInteractionRecord) -> None:
        await self._db.execute(
            insert(SessionInteractionRow).values(
                session_id=record.session_id,
                external_event_id=record.external_event_id,
                scene_before=record.scene_before,
                scene_after=record.scene_after,
                interaction_id=record.interaction_id,
                outcome_id=record.outcome_id,
                input_kind=record.input_kind.value,
                input_status=record.input_status.value,
                invalid_reason=(
                    record.invalid_reason.value
                    if record.invalid_reason is not None
                    else None
                ),
                created_at=record.created_at,
            )
        )
