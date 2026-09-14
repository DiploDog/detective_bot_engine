from __future__ import annotations

from pathlib import Path

import pytest

from detective_bot.adapters.telegram.runtime import (
    TelegramRuntime,
    validate_game_catalog,
)
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.settings import (
    SettingsError,
    TelegramSettings,
    load_telegram_settings,
)


ROOT = Path(__file__).resolve().parents[3]


def test_settings_require_token_and_database_url() -> None:
    with pytest.raises(SettingsError, match="TELEGRAM_BOT_TOKEN"):
        load_telegram_settings({})
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        load_telegram_settings({"TELEGRAM_BOT_TOKEN": "1:token"})
    with pytest.raises(SettingsError, match="postgresql\\+asyncpg"):
        load_telegram_settings(
            {
                "TELEGRAM_BOT_TOKEN": "1:token",
                "DATABASE_URL": "postgres://localhost/db",
            }
        )


def test_settings_load_from_environment() -> None:
    settings = load_telegram_settings(
        {
            "TELEGRAM_BOT_TOKEN": "1:token",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@127.0.0.1:5432/db",
            "GAMES_ROOT": str(ROOT / "games"),
            "LOG_LEVEL": "DEBUG",
            "TELEGRAM_DOCUMENT_ASSETS": "report_asset",
        }
    )
    assert settings.bot_token == "1:token"
    assert settings.document_asset_ids == frozenset({"report_asset"})
    assert settings.games_root == ROOT / "games"


async def test_runtime_setup_validates_catalog_without_polling() -> None:
    validate_game_catalog(FileSystemGameCatalog(ROOT / "games"))
    runtime = TelegramRuntime(
        TelegramSettings(
            bot_token="1:token",
            database_url="postgresql+asyncpg://user:pass@127.0.0.1:1/db",
            games_root=ROOT / "games",
        )
    )
    runtime.setup()
    assert runtime.bot is not None
    assert runtime.dispatcher is not None
    assert runtime.engine is not None
    await runtime.shutdown()
