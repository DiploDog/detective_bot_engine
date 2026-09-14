from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from detective_bot.application.models import (
    OutboundDelivery,
    OutboundDeliveryStatus,
    Platform,
    PlayerContext,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.infrastructure.postgres.models import (
    OutboundDeliveryRow,
    PlayerContextRow,
)
from detective_bot.infrastructure.postgres.sessions import (
    get_or_create_player_context,
)


class PostgresOutboundDeliveryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, deliveries: tuple[OutboundDelivery, ...]) -> None:
        if not deliveries:
            return
        player_id = await get_or_create_player_context(
            self._db,
            deliveries[0].player_context,
            now=deliveries[0].created_at,
        )
        values = [
            {
                "player_context_id": player_id,
                "session_id": item.session_id,
                "source_event_id": item.source_event_id,
                "sequence_no": item.sequence_no,
                "action_payload": dict(item.action_payload),
                "status": item.status.value,
                "due_at": item.due_at,
                "created_at": item.created_at,
                "attempts": item.attempts,
                "claimed_at": item.claimed_at,
                "lease_until": item.lease_until,
                "delivered_at": item.delivered_at,
                "next_attempt_at": item.next_attempt_at,
                "last_error_code": item.last_error_code,
            }
            for item in deliveries
        ]
        await self._db.execute(insert(OutboundDeliveryRow).values(values))

    async def cancel_pending_for_session(
        self,
        session_id: str,
        *,
        cancelled_at: datetime,
    ) -> None:
        del cancelled_at
        await self._db.execute(
            update(OutboundDeliveryRow)
            .where(
                OutboundDeliveryRow.session_id == session_id,
                OutboundDeliveryRow.status == OutboundDeliveryStatus.PENDING.value,
            )
            .values(status=OutboundDeliveryStatus.CANCELLED.value)
        )

    async def claim_due(
        self,
        platform: str,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        if limit <= 0:
            return ()
        statement = (
            select(OutboundDeliveryRow, PlayerContextRow)
            .join(
                PlayerContextRow,
                PlayerContextRow.id == OutboundDeliveryRow.player_context_id,
            )
            .where(
                PlayerContextRow.platform == platform,
                *_due_predicates(now),
            )
            .order_by(
                OutboundDeliveryRow.due_at,
                OutboundDeliveryRow.source_event_id,
                OutboundDeliveryRow.sequence_no,
                OutboundDeliveryRow.id,
            )
            .limit(limit)
            .with_for_update(of=OutboundDeliveryRow, skip_locked=True)
        )
        return await self._claim_rows(statement, now=now, lease_until=lease_until)

    async def claim_source_event(
        self,
        player_context: PlayerContext,
        source_event_id: str,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        statement = (
            select(OutboundDeliveryRow, PlayerContextRow)
            .join(
                PlayerContextRow,
                PlayerContextRow.id == OutboundDeliveryRow.player_context_id,
            )
            .where(
                PlayerContextRow.platform == player_context.platform.value,
                PlayerContextRow.external_user_id == player_context.external_user_id,
                PlayerContextRow.external_chat_id == player_context.external_chat_id,
                OutboundDeliveryRow.source_event_id == source_event_id,
                *_due_predicates(now),
            )
            .order_by(
                OutboundDeliveryRow.sequence_no,
                OutboundDeliveryRow.id,
            )
            .with_for_update(of=OutboundDeliveryRow)
        )
        return await self._claim_rows(statement, now=now, lease_until=lease_until)

    async def mark_delivered(
        self,
        delivery_id: int,
        *,
        delivered_at: datetime,
    ) -> None:
        result = await self._db.execute(
            update(OutboundDeliveryRow)
            .where(
                OutboundDeliveryRow.id == delivery_id,
                OutboundDeliveryRow.status == OutboundDeliveryStatus.CLAIMED.value,
            )
            .values(
                status=OutboundDeliveryStatus.DELIVERED.value,
                delivered_at=delivered_at,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"outbound delivery is not claimed: {delivery_id}")

    async def reschedule_after_failure(
        self,
        delivery_id: int,
        *,
        next_attempt_at: datetime,
        error_code: str,
    ) -> None:
        result = await self._db.execute(
            update(OutboundDeliveryRow)
            .where(
                OutboundDeliveryRow.id == delivery_id,
                OutboundDeliveryRow.status == OutboundDeliveryStatus.CLAIMED.value,
            )
            .values(
                status=OutboundDeliveryStatus.PENDING.value,
                next_attempt_at=next_attempt_at,
                last_error_code=error_code,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"outbound delivery is not claimed: {delivery_id}")

    async def mark_dead(
        self,
        delivery_id: int,
        *,
        error_code: str,
    ) -> None:
        result = await self._db.execute(
            update(OutboundDeliveryRow)
            .where(
                OutboundDeliveryRow.id == delivery_id,
                OutboundDeliveryRow.status == OutboundDeliveryStatus.CLAIMED.value,
            )
            .values(
                status=OutboundDeliveryStatus.DEAD.value,
                last_error_code=error_code,
                claimed_at=None,
                lease_until=None,
            )
        )
        if result.rowcount != 1:
            raise SessionConflict(f"outbound delivery is not claimed: {delivery_id}")

    async def release_expired_claims(self, *, now: datetime) -> int:
        result = await self._db.execute(
            update(OutboundDeliveryRow)
            .where(
                OutboundDeliveryRow.status == OutboundDeliveryStatus.CLAIMED.value,
                OutboundDeliveryRow.lease_until <= now,
            )
            .values(
                status=OutboundDeliveryStatus.PENDING.value,
                claimed_at=None,
                lease_until=None,
            )
        )
        return result.rowcount

    async def _claim_rows(
        self,
        statement,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> tuple[OutboundDelivery, ...]:
        rows = (await self._db.execute(statement)).all()
        claimed: list[OutboundDelivery] = []
        for delivery, player in rows:
            delivery.status = OutboundDeliveryStatus.CLAIMED.value
            delivery.claimed_at = now
            delivery.lease_until = lease_until
            delivery.attempts += 1
            claimed.append(_to_outbound_delivery(delivery, player))
        await self._db.flush()
        return tuple(claimed)


def _due_predicates(now: datetime) -> tuple:
    return (
        OutboundDeliveryRow.status == OutboundDeliveryStatus.PENDING.value,
        OutboundDeliveryRow.due_at <= now,
        or_(
            OutboundDeliveryRow.next_attempt_at.is_(None),
            OutboundDeliveryRow.next_attempt_at <= now,
        ),
    )


def _to_outbound_delivery(
    row: OutboundDeliveryRow,
    player: PlayerContextRow,
) -> OutboundDelivery:
    return OutboundDelivery(
        player_context=PlayerContext(
            platform=Platform(player.platform),
            external_user_id=player.external_user_id,
            external_chat_id=player.external_chat_id,
        ),
        session_id=row.session_id,
        source_event_id=row.source_event_id,
        sequence_no=row.sequence_no,
        action_payload=dict(row.action_payload),
        status=OutboundDeliveryStatus(row.status),
        due_at=row.due_at,
        created_at=row.created_at,
        attempts=row.attempts,
        claimed_at=row.claimed_at,
        lease_until=row.lease_until,
        delivered_at=row.delivered_at,
        next_attempt_at=row.next_attempt_at,
        last_error_code=row.last_error_code,
        delivery_id=row.id,
    )
