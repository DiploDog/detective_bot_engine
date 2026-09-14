from __future__ import annotations

import inspect

from vkbottle import (
    Callback,
    DocMessagesUploader,
    GroupEventType,
    Keyboard,
    PhotoMessageUploader,
    VKAPIError,
    VoiceMessageUploader,
)
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.polling.bot_polling import BotPolling

from detective_bot.adapters.telegram.callback_data import SelectGameCallback
from detective_bot.adapters.vk.callback_data import pack_payload


def test_vkbottle_group_long_poll_and_shutdown_hooks_exist() -> None:
    bot = Bot("0")
    assert isinstance(bot.polling, BotPolling)
    assert inspect.isasyncgenfunction(BotPolling.listen)
    assert callable(bot.polling.stop)
    assert inspect.iscoroutinefunction(bot.process_event)
    source = inspect.getsource(BotPolling.listen)
    assert "ClientConnectionError" in source
    assert "TimeoutError" in source
    assert "retry_count" in source
    assert inspect.iscoroutinefunction(bot.api.http_client.close)


def test_vkbottle_keyboard_callback_and_message_event() -> None:
    keyboard = Keyboard(inline=True)
    keyboard.add(Callback("Играть", pack_payload(SelectGameCallback("lora_dein"))))
    payload = keyboard.get_json()
    assert '"type": "callback"' in payload
    assert "lora_dein" in payload
    assert GroupEventType.MESSAGE_EVENT.value == "message_event"
    assert inspect.iscoroutinefunction(MessageEvent.send_empty_answer)
    assert inspect.iscoroutinefunction(MessageEvent.show_snackbar)


def test_vkbottle_text_photo_audio_document_surface() -> None:
    assert "text" in Message.model_fields
    assert inspect.iscoroutinefunction(PhotoMessageUploader.upload)
    assert inspect.iscoroutinefunction(DocMessagesUploader.upload)
    assert inspect.iscoroutinefunction(VoiceMessageUploader.upload)
    flood = VKAPIError[6](error_msg="too many requests per second")
    assert flood.code == 6
