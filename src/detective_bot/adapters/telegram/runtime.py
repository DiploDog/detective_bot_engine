from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine

from detective_bot.adapters.telegram.delivery import (
    TelegramDeliveryPump,
    TelegramDeliveryService,
)
from detective_bot.adapters.telegram.handlers import (
    TelegramUpdateProcessor,
    create_router,
)
from detective_bot.adapters.telegram.media import (
    CatalogMediaResolver,
    bot_id_from_token,
)
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.adapters.telegram.sender import AiogramTelegramSender
from detective_bot.infrastructure.postgres.media_cache import PostgresTelegramMediaCache
from detective_bot.application.service import ApplicationService
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres import (
    PostgresUnitOfWorkFactory,
    create_postgres_engine,
    create_session_factory,
)
from detective_bot.infrastructure.settings import TelegramSettings


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


class TelegramRuntime:
    def __init__(self, settings: TelegramSettings) -> None:
        self._settings = settings
        self.engine: AsyncEngine | None = None
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self._pump: TelegramDeliveryPump | None = None

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
        self.bot = Bot(self._settings.bot_token)
        sender = AiogramTelegramSender(self.bot)
        media_cache = PostgresTelegramMediaCache(session_factory)
        renderer = TelegramRenderer(
            sender=sender,
            resolver=CatalogMediaResolver(catalog, uow_factory),
            policy=TelegramMediaPolicy(self._settings.document_asset_ids),
            catalog=catalog,
            uow_factory=uow_factory,
            media_cache=media_cache,
            bot_id=bot_id_from_token(self._settings.bot_token),
            clock=utc_clock,
        )
        delivery = TelegramDeliveryService(
            uow_factory=uow_factory,
            renderer=renderer,
            catalog=catalog,
            clock=utc_clock,
        )
        processor = TelegramUpdateProcessor(service, renderer, uow_factory, delivery)
        self._pump = TelegramDeliveryPump(delivery)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(create_router(processor))

    async def start_polling(self) -> None:
        if self.dispatcher is None or self.bot is None or self._pump is None:
            raise RuntimeError("runtime is not set up")
        pump_task = self._pump.start()
        try:
            await self.dispatcher.start_polling(self.bot)
        finally:
            await self._pump.stop()
            if not pump_task.done():
                pump_task.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.bot is not None:
            await self.bot.session.close()
            self.bot = None
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
        self.dispatcher = None
