from __future__ import annotations

from detective_bot.adapters.telegram.callback_data import (
    CallbackDecodeError,
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    LeaveToMenuCallback,
    OpenMenuCallback,
    RequestRestartCallback,
    SelectGameCallback,
    TelegramCallback,
    pack_callback,
    unpack_callback,
)


PAYLOAD_KEY = "p"


def pack_payload(payload: TelegramCallback) -> dict[str, str]:
    return {PAYLOAD_KEY: pack_callback(payload)}


def unpack_payload(raw: object) -> TelegramCallback:
    if isinstance(raw, dict) and PAYLOAD_KEY in raw:
        return unpack_callback(str(raw[PAYLOAD_KEY]))
    if isinstance(raw, str):
        return unpack_callback(raw)
    raise CallbackDecodeError("malformed vk payload")
