from __future__ import annotations

from dataclasses import dataclass

from detective_bot.adapters.telegram.callback_data import (
    CALLBACK_DATA_LIMIT,
    CallbackDecodeError,
    CancelRestartCallback,
    ConfirmRestartCallback,
    decode_session_id,
    encode_session_id,
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
PAGE_CALLBACK_KIND = "v"


@dataclass(frozen=True, slots=True)
class ChoicesPageCallback:
    session_id: str
    revision: int
    interaction_id: str
    page: int


VkCallback = TelegramCallback | ChoicesPageCallback


def pack_payload(payload: VkCallback) -> dict[str, str]:
    if isinstance(payload, ChoicesPageCallback):
        if payload.revision < 0 or payload.page < 0:
            raise CallbackDecodeError("invalid choices page callback")
        interaction_id = _field(payload.interaction_id)
        packed = "|".join(
            (
                PAGE_CALLBACK_KIND,
                encode_session_id(payload.session_id),
                str(payload.revision),
                interaction_id,
                str(payload.page),
            )
        )
        if len(packed.encode("utf-8")) > CALLBACK_DATA_LIMIT:
            raise CallbackDecodeError("callback_data exceeds size limit")
    else:
        packed = pack_callback(payload)
    return {PAYLOAD_KEY: packed}


def unpack_payload(raw: object) -> VkCallback:
    if isinstance(raw, dict) and PAYLOAD_KEY in raw:
        packed = str(raw[PAYLOAD_KEY])
    elif isinstance(raw, str):
        packed = raw
    else:
        raise CallbackDecodeError("malformed vk payload")
    parts = packed.split("|")
    if parts[0] != PAGE_CALLBACK_KIND:
        return unpack_callback(packed)
    if len(parts) != 5:
        raise CallbackDecodeError("malformed choices page callback")
    try:
        revision = int(parts[2])
        page = int(parts[4])
    except ValueError as error:
        raise CallbackDecodeError("invalid choices page callback") from error
    if revision < 0 or page < 0:
        raise CallbackDecodeError("invalid choices page callback")
    return ChoicesPageCallback(
        session_id=decode_session_id(parts[1]),
        revision=revision,
        interaction_id=_field(parts[3]),
        page=page,
    )


def _field(value: str) -> str:
    if not value or "|" in value:
        raise CallbackDecodeError("callback field is empty or contains a delimiter")
    return value
