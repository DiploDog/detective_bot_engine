from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

from detective_bot.application.delivery import (
    OUTBOUND_CLAIM_LIMIT,
    OUTBOUND_LEASE_SECONDS,
    OUTBOUND_MAX_ATTEMPTS,
    ScheduledActionMaterializer,
    next_attempt_at,
    require_delivery_id,
)
from detective_bot.application.models import OutboundDelivery, PlayerContext
from detective_bot.application.outbound import OutboundSemantic, deserialize_action_payload
from detective_bot.application.ports import Clock, GameCatalogPort, UnitOfWorkFactory


logger = logging.getLogger(__name__)
PUMP_IDLE_SECONDS = 1.0

RetryAfterExtractor = Callable[[BaseException], float | None]


class SemanticRenderer(Protocol):
    async def render_semantic(
        self,
        chat_id: int,
        item: OutboundSemantic,
        *,
        session_id: str | None,
    ) -> None: ...


class PlatformDeliveryService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        renderer: SemanticRenderer,
        catalog: GameCatalogPort,
        clock: Clock,
        platform: str,
        retry_after: RetryAfterExtractor | None = None,
        max_attempts: int = OUTBOUND_MAX_ATTEMPTS,
        lease_seconds: int = OUTBOUND_LEASE_SECONDS,
        claim_limit: int = OUTBOUND_CLAIM_LIMIT,
    ) -> None:
        self._uow_factory = uow_factory
        self._renderer = renderer
        self._clock = clock
        self.platform = platform
        self._retry_after = retry_after or (lambda _error: None)
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._claim_limit = claim_limit
        self._materializer = ScheduledActionMaterializer(
            catalog=catalog,
            uow_factory=uow_factory,
            clock=clock,
            lease_seconds=lease_seconds,
        )

    async def tick(self) -> None:
        await self._materializer.materialize_due(self.platform)
        async with self._uow_factory() as uow:
            await uow.outbound_deliveries.release_expired_claims(now=self._clock())
            await uow.commit()
        await self.deliver_due()

    async def deliver_source_event(
        self,
        player_context: PlayerContext,
        source_event_id: str,
    ) -> None:
        now = self._clock()
        async with self._uow_factory() as uow:
            claimed = await uow.outbound_deliveries.claim_source_event(
                player_context,
                source_event_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
            )
            await uow.commit()
        await self._send_claimed(claimed)

    async def deliver_due(self) -> int:
        now = self._clock()
        async with self._uow_factory() as uow:
            claimed = await uow.outbound_deliveries.claim_due(
                self.platform,
                now=now,
                limit=self._claim_limit,
                lease_until=now + timedelta(seconds=self._lease_seconds),
            )
            await uow.commit()
        await self._send_claimed(claimed)
        return len(claimed)

    async def _send_claimed(self, claimed: tuple[OutboundDelivery, ...]) -> None:
        ordered = sorted(claimed, key=lambda item: (item.sequence_no, item.delivery_id or 0))
        for delivery in ordered:
            await self._send_one(delivery)

    async def _send_one(self, delivery: OutboundDelivery) -> None:
        delivery_id = require_delivery_id(delivery)
        now = self._clock()
        try:
            semantic = deserialize_action_payload(delivery.action_payload)
            await self._renderer.render_semantic(
                int(delivery.player_context.external_chat_id),
                semantic,
                session_id=delivery.session_id,
            )
        except Exception as error:
            retry_after = self._retry_after(error)
            if retry_after is not None:
                await self._retry(
                    delivery,
                    error_code=f"{self.platform}_retry_after",
                    retry_after=retry_after,
                )
                return
            logger.exception(
                "outbound delivery failed",
                extra={
                    "platform": self.platform,
                    "delivery_id": delivery_id,
                    "source_event_id": delivery.source_event_id,
                    "error_category": "delivery",
                },
            )
            await self._retry(delivery, error_code="send_failed")
            return
        async with self._uow_factory() as uow:
            await uow.outbound_deliveries.mark_delivered(
                delivery_id,
                delivered_at=now,
            )
            await uow.commit()

    async def _retry(
        self,
        delivery: OutboundDelivery,
        *,
        error_code: str,
        retry_after: float | None = None,
    ) -> None:
        delivery_id = require_delivery_id(delivery)
        now = self._clock()
        async with self._uow_factory() as uow:
            if delivery.attempts >= self._max_attempts:
                await uow.outbound_deliveries.mark_dead(
                    delivery_id,
                    error_code=error_code,
                )
            else:
                await uow.outbound_deliveries.reschedule_after_failure(
                    delivery_id,
                    next_attempt_at=next_attempt_at(
                        now,
                        attempts=delivery.attempts,
                        retry_after=retry_after,
                    ),
                    error_code=error_code,
                )
            await uow.commit()


class DeliveryPump:
    def __init__(
        self,
        delivery: PlatformDeliveryService,
        *,
        interval_seconds: float = PUMP_IDLE_SECONDS,
    ) -> None:
        self._delivery = delivery
        self._interval_seconds = interval_seconds
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        self._stopped.clear()
        self._task = asyncio.create_task(
            self.run(),
            name=f"{self._delivery.platform}-delivery-pump",
        )
        return self._task

    async def run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._delivery.tick()
            except Exception:
                logger.exception(
                    "delivery pump tick failed",
                    extra={
                        "platform": self._delivery.platform,
                        "error_category": "pump",
                    },
                )
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
