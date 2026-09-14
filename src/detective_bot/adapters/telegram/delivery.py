from __future__ import annotations

from aiogram.exceptions import TelegramRetryAfter

from detective_bot.adapters.delivery import (
    DeliveryPump,
    PlatformDeliveryService,
    PUMP_IDLE_SECONDS,
)
from detective_bot.adapters.telegram.renderer import TelegramRenderer
from detective_bot.application.ports import Clock, GameCatalogPort, UnitOfWorkFactory


class TelegramDeliveryService(PlatformDeliveryService):
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        renderer: TelegramRenderer,
        catalog: GameCatalogPort,
        clock: Clock,
        platform: str = "telegram",
        **kwargs,
    ) -> None:
        super().__init__(
            uow_factory=uow_factory,
            renderer=renderer,
            catalog=catalog,
            clock=clock,
            platform=platform,
            retry_after=_telegram_retry_after,
            **kwargs,
        )


class TelegramDeliveryPump(DeliveryPump):
    pass


def _telegram_retry_after(error: BaseException) -> float | None:
    if isinstance(error, TelegramRetryAfter):
        return float(error.retry_after)
    return None


__all__ = [
    "PUMP_IDLE_SECONDS",
    "TelegramDeliveryPump",
    "TelegramDeliveryService",
]
