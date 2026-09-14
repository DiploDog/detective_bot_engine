from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from vkbottle import API

from detective_bot.adapters.vk.sender import VkbottleVkSender


ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "games/killing_margo/1.0.0/assets/phone_recording.mp3"


async def test_audio_as_document_uploads_via_doc_messages_uploader_with_peer_id() -> None:
    assert AUDIO.is_file()
    sender = VkbottleVkSender(API("0"), community_id="123456")
    sender._docs.upload = AsyncMock(return_value="doc-123456_1")
    sender._send_message = AsyncMock()
    try:
        attachment = await sender.send_audio(22, AUDIO, "запись")
    finally:
        await sender._api.http_client.close()

    sender._docs.upload.assert_awaited_once_with(
        file_source=str(AUDIO),
        peer_id=22,
    )
    assert attachment == "doc-123456_1"
    sender._send_message.assert_awaited_once()
    kwargs = sender._docs.upload.await_args.kwargs
    assert "group_id" not in kwargs
    assert Path(kwargs["file_source"]).is_file()
