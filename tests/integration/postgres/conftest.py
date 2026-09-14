from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from detective_bot.application.models import (
    ApplicationSession,
    PlayerContext,
)
from detective_bot.engine.model import SessionSnapshot, SessionStatus
from detective_bot.infrastructure.postgres.database import (
    create_postgres_engine,
    create_session_factory,
)
from detective_bot.infrastructure.postgres.uow import (
    PostgresUnitOfWorkFactory,
)


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg")
    return url


@pytest.fixture(scope="session")
def alembic_config(test_database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        test_database_url.replace("%", "%%"),
    )
    return config


@pytest.fixture(scope="session", autouse=True)
def migrated_database(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest_asyncio.fixture
async def postgres_engine(
    test_database_url: str,
    migrated_database: None,
) -> AsyncEngine:
    del migrated_database
    engine = create_postgres_engine(test_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    postgres_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(postgres_engine)


@pytest_asyncio.fixture(autouse=True)
async def clean_database(postgres_engine: AsyncEngine):
    async def truncate() -> None:
        async with postgres_engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE vk_media_cache, telegram_media_cache, outbound_deliveries, "
                    "session_interactions, scheduled_actions, processed_events, "
                    "player_contexts, game_sessions RESTART IDENTITY CASCADE"
                )
            )

    await truncate()
    yield
    await truncate()


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> PostgresUnitOfWorkFactory:
    return PostgresUnitOfWorkFactory(session_factory)


@pytest.fixture
def session_builder() -> Callable[..., ApplicationSession]:
    def build(
        *,
        session_id: str,
        player: PlayerContext,
        game_id: str = "lora_dein",
        game_version: str = "1.0.0",
        current_scene: str = "lora_scene1",
        variables: dict | None = None,
        revision: int = 1,
        engine_status: SessionStatus = SessionStatus.IN_PROGRESS,
        completed_at: datetime | None = None,
    ) -> ApplicationSession:
        return ApplicationSession(
            player_context=player,
            engine_snapshot=SessionSnapshot(
                session_id=session_id,
                game_id=game_id,
                game_version=game_version,
                current_scene=current_scene,
                status=engine_status,
                variables=variables or {},
                revision=revision,
            ),
            created_at=NOW,
            updated_at=NOW,
            completed_at=completed_at,
        )

    return build
