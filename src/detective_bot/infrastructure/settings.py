from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import os


class SettingsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    bot_token: str
    database_url: str
    games_root: Path
    log_level: str = "INFO"
    document_asset_ids: frozenset[str] = frozenset()


def load_telegram_settings(
    environ: Mapping[str, str] | None = None,
) -> TelegramSettings:
    env = os.environ if environ is None else environ
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SettingsError("TELEGRAM_BOT_TOKEN is required")
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SettingsError("DATABASE_URL is required")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise SettingsError("DATABASE_URL must use postgresql+asyncpg")
    games_root = Path(env.get("GAMES_ROOT", "games")).expanduser()
    if not games_root.is_absolute():
        games_root = Path.cwd() / games_root
    log_level = env.get("LOG_LEVEL", "INFO").strip() or "INFO"
    raw_assets = env.get("TELEGRAM_DOCUMENT_ASSETS")
    if raw_assets is None:
        document_assets = frozenset({"final_police_report"})
    else:
        document_assets = frozenset(
            item.strip() for item in raw_assets.split(",") if item.strip()
        )
    return TelegramSettings(
        bot_token=token,
        database_url=database_url,
        games_root=games_root,
        log_level=log_level,
        document_asset_ids=document_assets,
    )


@dataclass(frozen=True, slots=True)
class VkSettings:
    group_token: str
    group_id: str
    database_url: str
    games_root: Path
    log_level: str = "INFO"
    document_asset_ids: frozenset[str] = frozenset()


def load_vk_settings(environ: Mapping[str, str] | None = None) -> VkSettings:
    env = os.environ if environ is None else environ
    token = env.get("VK_GROUP_TOKEN", "").strip()
    if not token:
        raise SettingsError("VK_GROUP_TOKEN is required")
    group_id = env.get("VK_GROUP_ID", "").strip()
    if not group_id:
        raise SettingsError("VK_GROUP_ID is required")
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SettingsError("DATABASE_URL is required")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise SettingsError("DATABASE_URL must use postgresql+asyncpg")
    games_root = Path(env.get("GAMES_ROOT", "games")).expanduser()
    if not games_root.is_absolute():
        games_root = Path.cwd() / games_root
    log_level = env.get("LOG_LEVEL", "INFO").strip() or "INFO"
    raw_assets = env.get("VK_DOCUMENT_ASSETS")
    if raw_assets is None:
        document_assets: frozenset[str] = frozenset()
    else:
        document_assets = frozenset(
            item.strip() for item in raw_assets.split(",") if item.strip()
        )
    return VkSettings(
        group_token=token,
        group_id=group_id,
        database_url=database_url,
        games_root=games_root,
        log_level=log_level,
        document_asset_ids=document_assets,
    )
