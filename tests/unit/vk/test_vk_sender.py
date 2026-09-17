from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, AsyncMock

from vkbottle import API

from detective_bot.adapters.vk.sender import VkbottleVkSender


ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "games/killing_margo/1.0.0/assets/phone_recording_vk.ogg"
DOCUMENT = ROOT / "games/killing_margo/1.0.0/assets/final_police_report.jpg"


async def test_document_upload_includes_community_and_peer_ids() -> None:
    assert DOCUMENT.is_file()
    sender = VkbottleVkSender(API("0"), community_id="123456")
    sender._docs.upload = AsyncMock(return_value="doc-123456_1")
    sender._send_message = AsyncMock()
    try:
        attachment = await sender.send_document(22, DOCUMENT, "отчёт")
    finally:
        await sender._api.http_client.close()

    sender._docs.upload.assert_awaited_once_with(
        file_source=str(DOCUMENT),
        group_id=123456,
        peer_id=22,
    )
    assert attachment == "doc-123456_1"
    sender._send_message.assert_awaited_once()


async def test_audio_uses_voice_upload_with_community_and_peer_ids() -> None:
    assert AUDIO.is_file()
    sender = VkbottleVkSender(API("0"), community_id="123456")
    sender._voices.upload = AsyncMock(return_value="audio_message-123456_1")
    sender._docs.upload = AsyncMock()
    sender._api.request = AsyncMock(return_value={"response": 1})
    try:
        attachment = await sender.send_audio(22, AUDIO, "запись")
    finally:
        await sender._api.http_client.close()

    sender._voices.upload.assert_awaited_once_with(
        file_source=str(AUDIO),
        group_id=123456,
        peer_id=22,
    )
    sender._docs.upload.assert_not_awaited()
    assert attachment == "audio_message-123456_1"
    sender._api.request.assert_awaited_once_with(
        "messages.send",
        {
            "peer_id": 22,
            "random_id": ANY,
            "message": "запись",
            "attachment": "audio_message-123456_1",
        },
    )
