from __future__ import annotations

import logging

from vkbottle import GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent

from detective_bot.adapters.vk.delivery import VkDeliveryService
from detective_bot.adapters.vk.inbound import (
    ChoicesPageRequest,
    GENERIC_USER_ERROR,
    IgnoredUpdate,
    RejectedUpdate,
    RestartSelectedCommand,
    map_message,
    map_message_event,
)
from detective_bot.adapters.vk.renderer import VkRenderer
from detective_bot.application.models import IncomingInteraction, OpenMenu, RequestRestart
from detective_bot.application.ports import UnitOfWorkFactory
from detective_bot.application.service import ApplicationService


logger = logging.getLogger(__name__)


class VkUpdateProcessor:
    def __init__(
        self,
        service: ApplicationService,
        renderer: VkRenderer,
        uow_factory: UnitOfWorkFactory,
        delivery: VkDeliveryService,
    ) -> None:
        self._service = service
        self._renderer = renderer
        self._uow_factory = uow_factory
        self._delivery = delivery

    async def process_message(self, message: Message) -> None:
        await self._process(map_message(message), message.peer_id, f"vk:message:{message.id}")

    async def process_message_event(self, event: MessageEvent) -> None:
        await self._process(
            map_message_event(event),
            event.peer_id,
            f"vk:event:{event.event_id}",
        )

    async def _process(
        self,
        inbound: (
            IncomingInteraction
            | RejectedUpdate
            | RestartSelectedCommand
            | ChoicesPageRequest
            | IgnoredUpdate
        ),
        peer_id: int,
        log_event_id: str,
    ) -> None:
        if isinstance(inbound, IgnoredUpdate):
            return
        if isinstance(inbound, RejectedUpdate):
            await self._renderer.send_notice(peer_id, inbound.text)
            return
        if isinstance(inbound, ChoicesPageRequest):
            await self._renderer.render_choices_page(peer_id, inbound)
            return
        try:
            interaction = await self._resolve(inbound)
            if interaction is None:
                await self._renderer.send_notice(peer_id, "Сначала выберите игру.")
                interaction = IncomingInteraction(
                    inbound.player_context,
                    OpenMenu(),
                    inbound.external_event_id,
                )
                await self._service.handle(interaction)
                await self._deliver(interaction)
                return
            logger.info(
                "vk interaction",
                extra={
                    "platform": "vk",
                    "external_event_id": interaction.external_event_id,
                    "action_type": type(interaction.action).__name__,
                },
            )
            await self._service.handle(interaction)
            await self._deliver(interaction)
        except Exception:
            logger.exception(
                "vk update failed",
                extra={
                    "platform": "vk",
                    "external_event_id": log_event_id,
                    "action_type": type(getattr(inbound, "action", inbound)).__name__,
                    "error_category": "unexpected",
                },
            )
            await self._renderer.send_notice(peer_id, GENERIC_USER_ERROR)

    async def _resolve(
        self,
        inbound: IncomingInteraction | RestartSelectedCommand,
    ) -> IncomingInteraction | None:
        if isinstance(inbound, IncomingInteraction):
            return inbound
        async with self._uow_factory() as uow:
            selected = await uow.sessions.get_selected(inbound.player_context)
        if selected is None:
            return None
        return IncomingInteraction(
            inbound.player_context,
            RequestRestart(selected.session_id),
            inbound.external_event_id,
        )

    async def _deliver(self, interaction: IncomingInteraction) -> None:
        if interaction.external_event_id is None:
            return
        await self._delivery.deliver_source_event(
            interaction.player_context,
            interaction.external_event_id,
        )


def register_handlers(bot: Bot, processor: VkUpdateProcessor) -> None:
    @bot.on.message()
    async def on_message(message: Message) -> None:
        await processor.process_message(message)

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=MessageEvent)
    async def on_message_event(event: MessageEvent) -> None:
        try:
            await event.send_empty_answer()
        except Exception:
            logger.warning(
                "callback acknowledgement failed",
                extra={
                    "platform": "vk",
                    "external_event_id": f"vk:event:{event.event_id}",
                    "error_category": "callback_ack",
                },
            )
        await processor.process_message_event(event)
