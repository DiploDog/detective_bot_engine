from __future__ import annotations

from vkbottle import VKAPIError

from detective_bot.adapters.delivery import DeliveryPump, PlatformDeliveryService
from detective_bot.adapters.vk.renderer import VkRenderer
from detective_bot.adapters.vk.sender import VK_FLOOD_CODES
from detective_bot.application.ports import Clock, GameCatalogPort, UnitOfWorkFactory


class VkDeliveryService(PlatformDeliveryService):
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        renderer: VkRenderer,
        catalog: GameCatalogPort,
        clock: Clock,
        platform: str = "vk",
        **kwargs,
    ) -> None:
        super().__init__(
            uow_factory=uow_factory,
            renderer=renderer,
            catalog=catalog,
            clock=clock,
            platform=platform,
            retry_after=_vk_retry_after,
            **kwargs,
        )


class VkDeliveryPump(DeliveryPump):
    pass


def _vk_retry_after(error: BaseException) -> float | None:
    if isinstance(error, VKAPIError) and error.code in VK_FLOOD_CODES:
        return 1.0 if error.code == 6 else 3.0
    return None
