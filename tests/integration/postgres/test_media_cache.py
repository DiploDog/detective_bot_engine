from __future__ import annotations

from pathlib import Path

from detective_bot.adapters.telegram.media import ResolvedMedia, sha256_file
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.application.models import ApplicationResult, GameActions
from detective_bot.engine.model import MediaAction
from detective_bot.infrastructure.postgres.media_cache import PostgresTelegramMediaCache
from tests.fakes import MappingMediaResolver, RecordingTelegramSender
from tests.integration.postgres.conftest import NOW, ROOT
from tests.unit.telegram.conftest import CHAT_ID


IMAGE = ROOT / "games/killing_margo/1.0.0/assets/safe_closed.jpg"
AUDIO = ROOT / "games/killing_margo/1.0.0/assets/phone_recording.mp3"
REPORT = ROOT / "games/killing_margo/1.0.0/assets/final_police_report.jpg"


def make_renderer(
    cache: PostgresTelegramMediaCache,
    sender: RecordingTelegramSender,
    *,
    bot_id: str = "77",
) -> TelegramRenderer:
    return TelegramRenderer(
        sender=sender,
        resolver=MappingMediaResolver(
            {
                "closed": ResolvedMedia("closed", "image", IMAGE),
                "voice": ResolvedMedia("voice", "audio", AUDIO),
                "final_police_report": ResolvedMedia(
                    "final_police_report",
                    "image",
                    REPORT,
                ),
            }
        ),
        policy=TelegramMediaPolicy(
            document_asset_ids=frozenset({"final_police_report"})
        ),
        media_cache=cache,
        bot_id=bot_id,
        clock=lambda: NOW,
    )


async def render_closed(renderer: TelegramRenderer) -> None:
    await renderer.render(
        CHAT_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(MediaAction(type="media", asset="closed"),),
                ),
            )
        ),
    )


async def test_media_cache_miss_uploads_and_stores_file_id(
    session_factory,
) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    assert sender.calls[0].path == IMAGE
    stored = await cache.get("77", sha256_file(IMAGE), "photo")
    assert stored == sender.calls[0].file_id
    assert stored is not None


async def test_media_cache_hit_reuses_file_id(session_factory) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    sender.calls.clear()
    await render_closed(renderer)
    assert sender.calls[0].path is None
    assert sender.calls[0].file_id == "uploaded:photo:safe_closed.jpg"


async def test_stale_file_id_falls_back_and_refreshes(session_factory) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    sender.stale_file_ids.add("stale-id")
    await cache.put("77", sha256_file(IMAGE), "photo", "stale-id", now=NOW)
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    assert sender.calls[0].path == IMAGE
    assert await cache.get("77", sha256_file(IMAGE), "photo") == (
        "uploaded:photo:safe_closed.jpg"
    )


async def test_other_bot_id_does_not_reuse_cache(session_factory) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    renderer = make_renderer(cache, sender, bot_id="77")
    await render_closed(renderer)
    sender.calls.clear()
    other = make_renderer(cache, sender, bot_id="88")
    await render_closed(other)
    assert sender.calls[0].path == IMAGE


async def test_other_sha_does_not_reuse_cache(session_factory) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    sender.calls.clear()
    await renderer.render(
        CHAT_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(MediaAction(type="media", asset="voice"),),
                ),
            )
        ),
    )
    assert sender.calls[0].path == AUDIO
    assert sender.calls[0].method == "audio"


async def test_final_police_report_uses_document_kind(session_factory) -> None:
    cache = PostgresTelegramMediaCache(session_factory)
    sender = RecordingTelegramSender()
    renderer = make_renderer(cache, sender)
    await renderer.render(
        CHAT_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(
                        MediaAction(type="media", asset="final_police_report"),
                    ),
                ),
            )
        ),
    )
    assert sender.calls[0].method == "document"
    assert await cache.get("77", sha256_file(REPORT), "document")
    assert await cache.get("77", sha256_file(REPORT), "photo") is None
