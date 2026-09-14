from __future__ import annotations

from detective_bot.adapters.media import ResolvedMedia, sha256_file
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.application.models import ApplicationResult, GameActions
from detective_bot.engine.model import MediaAction
from detective_bot.infrastructure.postgres.media_cache import PostgresVkMediaCache
from tests.fakes import MappingMediaResolver, RecordingVkSender
from tests.integration.postgres.conftest import NOW, ROOT
from tests.unit.vk.conftest import PEER_ID


IMAGE = ROOT / "games/killing_margo/1.0.0/assets/safe_closed.jpg"
AUDIO = ROOT / "games/killing_margo/1.0.0/assets/phone_recording.mp3"
REPORT = ROOT / "games/killing_margo/1.0.0/assets/final_police_report.jpg"


def make_renderer(
    cache: PostgresVkMediaCache,
    sender: RecordingVkSender,
    *,
    community_id: str = "100",
) -> VkRenderer:
    return VkRenderer(
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
        policy=VkMediaPolicy(),
        media_cache=cache,
        community_id=community_id,
        clock=lambda: NOW,
    )


async def render_closed(renderer: VkRenderer) -> None:
    await renderer.render(
        PEER_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(MediaAction(type="media", asset="closed"),),
                ),
            )
        ),
    )


async def test_media_cache_miss_uploads_and_stores_attachment(
    session_factory,
) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    assert sender.calls[0].path == IMAGE
    stored = await cache.get("100", sha256_file(IMAGE), "photo")
    assert stored == sender.calls[0].file_id
    assert stored is not None


async def test_media_cache_hit_reuses_attachment(session_factory) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    sender.calls.clear()
    await render_closed(renderer)
    assert sender.calls[0].path is None
    assert sender.calls[0].file_id == "uploaded:photo:safe_closed.jpg"


async def test_stale_attachment_falls_back_and_refreshes(session_factory) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    sender.stale_file_ids.add("stale-id")
    await cache.put("100", sha256_file(IMAGE), "photo", "stale-id", now=NOW)
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    assert sender.calls[0].path == IMAGE
    assert await cache.get("100", sha256_file(IMAGE), "photo") == (
        "uploaded:photo:safe_closed.jpg"
    )


async def test_other_community_id_does_not_reuse_cache(session_factory) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    renderer = make_renderer(cache, sender, community_id="100")
    await render_closed(renderer)
    sender.calls.clear()
    other = make_renderer(cache, sender, community_id="200")
    await render_closed(other)
    assert sender.calls[0].path == IMAGE


async def test_audio_kind_does_not_reuse_photo_cache(session_factory) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    renderer = make_renderer(cache, sender)
    await render_closed(renderer)
    sender.calls.clear()
    await renderer.render(
        PEER_ID,
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


async def test_final_police_report_uses_photo_kind(session_factory) -> None:
    cache = PostgresVkMediaCache(session_factory)
    sender = RecordingVkSender()
    renderer = make_renderer(cache, sender)
    await renderer.render(
        PEER_ID,
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
    assert sender.calls[0].method == "photo"
    assert await cache.get("100", sha256_file(REPORT), "photo")
    assert await cache.get("100", sha256_file(REPORT), "document") is None
