from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message, Update

from detective_bot.adapters.telegram.inbound import (
    GENERIC_USER_ERROR,
    IgnoredUpdate,
    RejectedUpdate,
    RestartSelectedCommand,
    map_update,
)
from detective_bot.adapters.telegram.delivery import TelegramDeliveryService
from detective_bot.adapters.telegram.renderer import TelegramRenderer
from detective_bot.application.models import IncomingInteraction, OpenMenu, RequestRestart
from detective_bot.application.ports import UnitOfWorkFactory
from detective_bot.application.service import ApplicationService

logger = logging.getLogger(__name__)


class TelegramUpdateProcessor:
    def __init__(
        self,
        service: ApplicationService,
        renderer: TelegramRenderer,
        uow_factory: UnitOfWorkFactory,
        delivery: TelegramDeliveryService,
    ) -> None:
        self._service = service
        self._renderer = renderer
        self._uow_factory = uow_factory
        self._delivery = delivery

    async def process_update(self, update: Update) -> None:
        inbound = map_update(update)
        chat_id = _chat_id(update)
        if isinstance(inbound, IgnoredUpdate) or chat_id is None:
            return
        if isinstance(inbound, RejectedUpdate):
            await self._renderer.send_notice(chat_id, inbound.text)
            return
        try:
            interaction = await self._resolve(inbound)
            if interaction is None:
                await self._renderer.send_notice(chat_id, "Сначала выберите игру.")
                interaction = IncomingInteraction(
                    inbound.player_context,
                    OpenMenu(),
                    inbound.external_event_id,
                )
                await self._service.handle(interaction)
                await self._deliver(interaction)
                return
            logger.info(
                "telegram interaction",
                extra={
                    "platform": "telegram",
                    "external_event_id": interaction.external_event_id,
                    "action_type": type(interaction.action).__name__,
                },
            )
            await self._service.handle(interaction)
            await self._deliver(interaction)
        except Exception:
            logger.exception(
                "telegram update failed",
                extra={
                    "platform": "telegram",
                    "external_event_id": f"telegram:{update.update_id}",
                    "action_type": type(getattr(inbound, "action", inbound)).__name__,
                    "error_category": "unexpected",
                },
            )
            await self._renderer.send_notice(chat_id, GENERIC_USER_ERROR)

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


def create_router(processor: TelegramUpdateProcessor) -> Router:
    router = Router()

    @router.message()
    async def on_message(message: Message, event_update: Update) -> None:
        del message
        await processor.process_update(event_update)

    @router.callback_query()
    async def on_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            await callback.answer()
        except Exception:
            logger.warning(
                "callback acknowledgement failed",
                extra={
                    "platform": "telegram",
                    "external_event_id": f"telegram:{event_update.update_id}",
                    "error_category": "callback_ack",
                },
            )
        await processor.process_update(event_update)

    return router


def _chat_id(update: Update) -> int | None:
    if update.message is not None and update.message.chat is not None:
        return update.message.chat.id
    callback = update.callback_query
    if callback is not None and isinstance(callback.message, Message):
        return callback.message.chat.id
    return None
