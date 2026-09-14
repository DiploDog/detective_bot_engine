from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from detective_bot.infrastructure.postgres.database import create_postgres_engine


async def table_names(database_url: str) -> set[str]:
    engine = create_postgres_engine(database_url)
    async with engine.connect() as connection:
        names = set(
            await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        )
    await engine.dispose()
    return names


def test_downgrade_base_and_upgrade_head_create_expected_schema(
    alembic_config: Config,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    assert asyncio.run(table_names(test_database_url)) == {"alembic_version"}

    command.upgrade(alembic_config, "head")
    assert {
        "player_contexts",
        "game_sessions",
        "processed_events",
        "scheduled_actions",
        "session_interactions",
        "outbound_deliveries",
        "telegram_media_cache",
        "vk_media_cache",
    }.issubset(asyncio.run(table_names(test_database_url)))


def test_upgrade_from_0001_creates_outbound_deliveries(
    alembic_config: Config,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "20260905_0001")
    names_at_0001 = asyncio.run(table_names(test_database_url))
    assert "outbound_deliveries" not in names_at_0001
    assert {
        "player_contexts",
        "game_sessions",
        "processed_events",
        "scheduled_actions",
        "session_interactions",
    }.issubset(names_at_0001)

    command.upgrade(alembic_config, "head")
    names = asyncio.run(table_names(test_database_url))
    assert "outbound_deliveries" in names
    assert "telegram_media_cache" in names
    assert "vk_media_cache" in names
