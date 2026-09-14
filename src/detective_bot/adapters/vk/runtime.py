from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine
from vkbottle.bot import Bot

from detective_bot.adapters.media import CatalogMediaResolver
from detective_bot.adapters.vk.delivery import VkDeliveryPump, VkDeliveryService
from detective_bot.adapters.vk.handlers import VkUpdateProcessor, register_handlers
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.adapters.vk.sender import VkbottleVkSender
from detective_bot.application.service import ApplicationService
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres import (
    PostgresUnitOfWorkFactory,
    create_postgres_engine,
    create_session_factory,
)
from detective_bot.infrastructure.postgres.media_cache import PostgresVkMediaCache
from detective_bot.infrastructure.settings import VkSettings


logger = logging.getLogger(__name__)


class CatalogValidationError(RuntimeError):
    pass


def utc_clock() -> datetime:
    return datetime.now(UTC)


def new_session_id() -> str:
    return uuid4().hex


def validate_game_catalog(catalog: FileSystemGameCatalog) -> None:
    scan = catalog.scan()
    if scan.failures:
        raise CatalogValidationError(
            f"game catalog has invalid packages: {len(scan.failures)}"
        )
    if not scan.packages:
        raise CatalogValidationError("game catalog does not contain installed games")


class VkRuntime:
    def __init__(self, settings: VkSettings) -> None:
        self._settings = settings
        self.engine: AsyncEngine | None = None
        self.bot: Bot | None = None
        self._pump: VkDeliveryPump | None = None

    def setup(self) -> None:
        logging.basicConfig(level=self._settings.log_level)
        catalog = FileSystemGameCatalog(self._settings.games_root)
        validate_game_catalog(catalog)
        self.engine = create_postgres_engine(self._settings.database_url)
        session_factory = create_session_factory(self.engine)
        uow_factory = PostgresUnitOfWorkFactory(session_factory)
        service = ApplicationService(
            catalog=catalog,
            uow_factory=uow_factory,
            engine=GameEngine(),
            clock=utc_clock,
            session_id_factory=new_session_id,
        )
        self.bot = Bot(self._settings.group_token)
        sender = VkbottleVkSender(self.bot.api, community_id=self._settings.group_id)
        media_cache = PostgresVkMediaCache(session_factory)
        renderer = VkRenderer(
            sender=sender,
            resolver=CatalogMediaResolver(catalog, uow_factory),
            policy=VkMediaPolicy(self._settings.document_asset_ids),
            catalog=catalog,
            uow_factory=uow_factory,
            media_cache=media_cache,
            community_id=self._settings.group_id,
            clock=utc_clock,
        )
        delivery = VkDeliveryService(
            uow_factory=uow_factory,
            renderer=renderer,
            catalog=catalog,
            clock=utc_clock,
        )
        processor = VkUpdateProcessor(service, renderer, uow_factory, delivery)
        self._pump = VkDeliveryPump(delivery)
        register_handlers(self.bot, processor)

    async def start_polling(self) -> None:
        if self.bot is None or self._pump is None:
            raise RuntimeError("runtime is not set up")
        pump_task = self._pump.start()
        try:
            async for envelope in self.bot.polling.listen():
                await dispatch_long_poll_envelope(self.bot, envelope)
        finally:
            self.bot.polling.stop()
            await self._pump.stop()
            if not pump_task.done():
                pump_task.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.bot is not None:
            await self.bot.api.http_client.close()
            self.bot = None
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None


def long_poll_updates(envelope: object) -> tuple[dict, ...]:
    if not isinstance(envelope, dict):
        return ()
    raw_updates = envelope.get("updates")
    if not isinstance(raw_updates, list):
        return ()
    return tuple(
        update
        for update in raw_updates
        if isinstance(update, dict) and "type" in update
    )


async def dispatch_long_poll_envelope(bot: Bot, envelope: object) -> None:
    for update in long_poll_updates(envelope):
        await bot.process_event(update)
