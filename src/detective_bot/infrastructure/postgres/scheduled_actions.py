from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from detective_bot.application.models import (
    Platform,
    PlayerContext,
    ScheduledActionStatus,
    StoredScheduledAction,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.engine.model import ScheduledActionRequest
from detective_bot.infrastructure.postgres.models import (
    GameSessionRow,
    PlayerContextRow,
    ScheduledActionRow,
)


class PostgresScheduledActionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(
        self,
        session_id: str,
        origin_revision: int,
        requests: tuple[ScheduledActionRequest, ...],
        *,
        created_at: datetime,
    ) -> None:
        if not requests:
            return
        values = [
            {
                "session_id": session_id,
                "template_id": request.template_id,
                "origin_revision": origin_revision,
                "due_at": request.due_at,
                "idempotency_key": request.idempotency_key,
                "status": ScheduledActionStatus.PENDING.value,
                "attempts": 0,
                "created_at": created_at,
            }
            for request in requests
        ]
        await self._db.execute(
            insert(ScheduledActionRow)
            .values(values)
            .on_conflict_do_nothing(
                constraint="uq_scheduled_action_idempotency"
            )
        )

    async def cancel_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None:
        await self._db.execute(
            update(ScheduledActionRow)
            .where(
                ScheduledActionRow.session_id == session_id,
                ScheduledActionRow.status.in_(
                    (
                        ScheduledActionStatus.PENDING.value,
                        ScheduledActionStatus.CLAIMED.value,
                    )
                ),
            )
            .values(
                status=ScheduledActionStatus.CANCELLED.value,
                cancelled_at=cancelled_at,
                claimed_at=None,
                lease_until=None,
            )
        )

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[StoredScheduledAction, ...]:
        if limit <= 0:
            return ()
        statement = (
            select(ScheduledActionRow, GameSessionRow, PlayerContextRow)
            .join(
                GameSessionRow,
                GameSessionRow.id == ScheduledActionRow.session_id,
            )
            .join(
                PlayerContextRow,
                PlayerContextRow.id == GameSessionRow.player_context_id,
            )
            .where(
                PlayerContextRow.platform == platform,
                ScheduledActionRow.status
                == ScheduledActionStatus.PENDING.value,
                ScheduledActionRow.due_at <= now,
                or_(
                    ScheduledActionRow.next_attempt_at.is_(None),
                    ScheduledActionRow.next_attempt_at <= now,
                ),
            )
            .order_by(ScheduledActionRow.due_at, ScheduledActionRow.id)
            .limit(limit)
            .with_for_update(of=ScheduledActionRow, skip_locked=True)
        )
        rows = (await self._db.execute(statement)).all()
        claimed: list[StoredScheduledAction] = []
        for action, game_session, player in rows:
            action.status = ScheduledActionStatus.CLAIMED.value
            action.claimed_at = now
            action.lease_until = lease_until
            action.attempts += 1
            claimed.append(_to_stored_action(action, game_session, player))
        await self._db.flush()
        return tuple(claimed)

    async def mark_delivered(
        self,
        action_id: int,
        *,
        delivered_at: datetime,
    ) -> None:
        result = await self._db.execute(
            update(ScheduledActionRow)
            .where(
                ScheduledActionRow.id == action_id,
                ScheduledActionRow.status
                == ScheduledActionStatus.CLAIMED.value,
            )
            .values(
                status=ScheduledActionStatus.DELIVERED.value,
                delivered_at=delivered_at,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"scheduled action is not claimed: {action_id}")

    async def reschedule_after_failure(
        self,
        action_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None:
        result = await self._db.execute(
            update(ScheduledActionRow)
            .where(
                ScheduledActionRow.id == action_id,
                ScheduledActionRow.status
                == ScheduledActionStatus.CLAIMED.value,
            )
            .values(
                status=ScheduledActionStatus.PENDING.value,
                next_attempt_at=next_attempt_at,
                last_error_code=error_code,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"scheduled action is not claimed: {action_id}")

    async def release_expired_claims(self, *, now: datetime) -> int:
        result = await self._db.execute(
            update(ScheduledActionRow)
            .where(
                ScheduledActionRow.status
                == ScheduledActionStatus.CLAIMED.value,
                ScheduledActionRow.lease_until <= now,
            )
            .values(
                status=ScheduledActionStatus.PENDING.value,
                claimed_at=None,
                lease_until=None,
            )
        )
        return result.rowcount

    async def mark_cancelled(
        self,
        action_id: int,
        *,
        cancelled_at: datetime,
    ) -> None:
        result = await self._db.execute(
            update(ScheduledActionRow)
            .where(
                ScheduledActionRow.id == action_id,
                ScheduledActionRow.status.in_(
                    (
                        ScheduledActionStatus.PENDING.value,
                        ScheduledActionStatus.CLAIMED.value,
                    )
                ),
            )
            .values(
                status=ScheduledActionStatus.CANCELLED.value,
                cancelled_at=cancelled_at,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"scheduled action cannot be cancelled: {action_id}")


def _to_stored_action(
    action: ScheduledActionRow,
    game_session: GameSessionRow,
    player: PlayerContextRow,
) -> StoredScheduledAction:
    return StoredScheduledAction(
        action_id=action.id,
        session_id=action.session_id,
        player_context=PlayerContext(
            platform=Platform(player.platform),
            external_user_id=player.external_user_id,
            external_chat_id=player.external_chat_id,
        ),
        game_id=game_session.game_id,
        game_version=game_session.game_version,
        template_id=action.template_id,
        origin_revision=action.origin_revision,
        due_at=action.due_at,
        idempotency_key=action.idempotency_key,
        status=ScheduledActionStatus(action.status),
        attempts=action.attempts,
        claimed_at=action.claimed_at,
        lease_until=action.lease_until,
        delivered_at=action.delivered_at,
        cancelled_at=action.cancelled_at,
        next_attempt_at=action.next_attempt_at,
        last_error_code=action.last_error_code,
        created_at=action.created_at,
    )
