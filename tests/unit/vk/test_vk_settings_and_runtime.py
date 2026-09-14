from __future__ import annotations

from pathlib import Path

import pytest

from detective_bot.adapters.vk.runtime import (
    VkRuntime,
    dispatch_long_poll_envelope,
    validate_game_catalog,
)
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.settings import SettingsError, VkSettings, load_vk_settings


ROOT = Path(__file__).resolve().parents[3]


def test_settings_require_token_group_id_and_database_url() -> None:
    with pytest.raises(SettingsError, match="VK_GROUP_TOKEN"):
        load_vk_settings({})
    with pytest.raises(SettingsError, match="VK_GROUP_ID"):
        load_vk_settings({"VK_GROUP_TOKEN": "token"})
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        load_vk_settings({"VK_GROUP_TOKEN": "token", "VK_GROUP_ID": "100"})
    with pytest.raises(SettingsError, match="postgresql\\+asyncpg"):
        load_vk_settings(
            {
                "VK_GROUP_TOKEN": "token",
                "VK_GROUP_ID": "100",
                "DATABASE_URL": "postgres://localhost/db",
            }
        )


def test_settings_load_from_environment() -> None:
    settings = load_vk_settings(
        {
            "VK_GROUP_TOKEN": "group-token",
            "VK_GROUP_ID": "100",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@127.0.0.1:5432/db",
            "GAMES_ROOT": str(ROOT / "games"),
            "LOG_LEVEL": "DEBUG",
            "VK_DOCUMENT_ASSETS": "report_asset",
        }
    )
    assert settings.group_token == "group-token"
    assert settings.group_id == "100"
    assert settings.document_asset_ids == frozenset({"report_asset"})
    assert settings.games_root == ROOT / "games"


def test_settings_default_document_assets_are_empty() -> None:
    settings = load_vk_settings(
        {
            "VK_GROUP_TOKEN": "group-token",
            "VK_GROUP_ID": "100",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@127.0.0.1:5432/db",
        }
    )
    assert settings.document_asset_ids == frozenset()


async def test_long_poll_control_and_malformed_envelopes_are_not_dispatched() -> None:
    class RecordingBot:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def process_event(self, event: dict) -> None:
            if "type" not in event:
                raise KeyError("type")
            self.events.append(event)

    bot = RecordingBot()
    update = {"type": "message_new", "object": {"message": {"id": 1}}}
    await dispatch_long_poll_envelope(bot, {"ts": "10"})
    await dispatch_long_poll_envelope(bot, {"failed": 2, "ts": "11"})
    await dispatch_long_poll_envelope(bot, {"ts": "12", "updates": [{"object": {}}]})
    await dispatch_long_poll_envelope(
        bot,
        {"ts": "13", "updates": [update, {"failed": 1}]},
    )
    assert bot.events == [update]


async def test_runtime_setup_validates_catalog_without_polling() -> None:
    validate_game_catalog(FileSystemGameCatalog(ROOT / "games"))
    runtime = VkRuntime(
        VkSettings(
            group_token="token",
            group_id="100",
            database_url="postgresql+asyncpg://user:pass@127.0.0.1:1/db",
            games_root=ROOT / "games",
        )
    )
    runtime.setup()
    assert runtime.bot is not None
    assert runtime.engine is not None
    await runtime.shutdown()
