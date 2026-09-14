from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from enum import StrEnum
import re

from detective_bot.engine.model import ChoiceValue


CALLBACK_DATA_LIMIT = 64
_SEPARATOR = "|"
_HEX_SESSION = re.compile(r"^[0-9a-f]{32}$")


class CallbackKind(StrEnum):
    OPEN_MENU = "m"
    SELECT_GAME = "s"
    LEAVE_TO_MENU = "l"
    REQUEST_RESTART = "r"
    CONFIRM_RESTART = "y"
    CANCEL_RESTART = "n"
    GAME_CHOICE = "g"


class CallbackDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OpenMenuCallback:
    kind: CallbackKind = CallbackKind.OPEN_MENU


@dataclass(frozen=True, slots=True)
class SelectGameCallback:
    game_id: str
    kind: CallbackKind = CallbackKind.SELECT_GAME


@dataclass(frozen=True, slots=True)
class LeaveToMenuCallback:
    kind: CallbackKind = CallbackKind.LEAVE_TO_MENU


@dataclass(frozen=True, slots=True)
class RequestRestartCallback:
    session_id: str
    kind: CallbackKind = CallbackKind.REQUEST_RESTART


@dataclass(frozen=True, slots=True)
class ConfirmRestartCallback:
    session_id: str
    kind: CallbackKind = CallbackKind.CONFIRM_RESTART


@dataclass(frozen=True, slots=True)
class CancelRestartCallback:
    session_id: str
    kind: CallbackKind = CallbackKind.CANCEL_RESTART


@dataclass(frozen=True, slots=True)
class GameChoiceCallback:
    session_id: str
    revision: int
    interaction_id: str
    value: ChoiceValue
    kind: CallbackKind = CallbackKind.GAME_CHOICE


TelegramCallback = (
    OpenMenuCallback
    | SelectGameCallback
    | LeaveToMenuCallback
    | RequestRestartCallback
    | ConfirmRestartCallback
    | CancelRestartCallback
    | GameChoiceCallback
)


def pack_callback(payload: TelegramCallback) -> str:
    if isinstance(payload, OpenMenuCallback):
        packed = CallbackKind.OPEN_MENU.value
    elif isinstance(payload, LeaveToMenuCallback):
        packed = CallbackKind.LEAVE_TO_MENU.value
    elif isinstance(payload, SelectGameCallback):
        packed = _join(CallbackKind.SELECT_GAME.value, _field(payload.game_id))
    elif isinstance(payload, RequestRestartCallback):
        packed = _join(
            CallbackKind.REQUEST_RESTART.value,
            encode_session_id(payload.session_id),
        )
    elif isinstance(payload, ConfirmRestartCallback):
        packed = _join(
            CallbackKind.CONFIRM_RESTART.value,
            encode_session_id(payload.session_id),
        )
    elif isinstance(payload, CancelRestartCallback):
        packed = _join(
            CallbackKind.CANCEL_RESTART.value,
            encode_session_id(payload.session_id),
        )
    elif isinstance(payload, GameChoiceCallback):
        packed = _join(
            CallbackKind.GAME_CHOICE.value,
            encode_session_id(payload.session_id),
            str(payload.revision),
            _field(payload.interaction_id),
            *_encode_value(payload.value),
        )
    else:
        raise CallbackDecodeError(f"unsupported callback: {type(payload)!r}")
    if len(packed.encode("utf-8")) > CALLBACK_DATA_LIMIT:
        raise CallbackDecodeError("callback_data exceeds Telegram size limit")
    return packed


def unpack_callback(data: str) -> TelegramCallback:
    if not data:
        raise CallbackDecodeError("empty callback_data")
    parts = data.split(_SEPARATOR)
    kind = parts[0]
    if kind == CallbackKind.OPEN_MENU and len(parts) == 1:
        return OpenMenuCallback()
    if kind == CallbackKind.LEAVE_TO_MENU and len(parts) == 1:
        return LeaveToMenuCallback()
    if kind == CallbackKind.SELECT_GAME and len(parts) == 2:
        return SelectGameCallback(game_id=parts[1])
    if kind == CallbackKind.REQUEST_RESTART and len(parts) == 2:
        return RequestRestartCallback(session_id=decode_session_id(parts[1]))
    if kind == CallbackKind.CONFIRM_RESTART and len(parts) == 2:
        return ConfirmRestartCallback(session_id=decode_session_id(parts[1]))
    if kind == CallbackKind.CANCEL_RESTART and len(parts) == 2:
        return CancelRestartCallback(session_id=decode_session_id(parts[1]))
    if kind == CallbackKind.GAME_CHOICE and len(parts) == 5:
        return GameChoiceCallback(
            session_id=decode_session_id(parts[1]),
            revision=_parse_revision(parts[2]),
            interaction_id=parts[3],
            value=_decode_value(parts[4]),
        )
    raise CallbackDecodeError("malformed callback_data")


def encode_session_id(session_id: str) -> str:
    _field(session_id)
    if _HEX_SESSION.fullmatch(session_id) is not None:
        return "h" + urlsafe_b64encode(bytes.fromhex(session_id)).decode(
            "ascii"
        ).rstrip("=")
    return "p" + session_id


def decode_session_id(token: str) -> str:
    if not token:
        raise CallbackDecodeError("empty session token")
    prefix, raw = token[0], token[1:]
    if prefix == "h":
        padded = raw + "=" * (-len(raw) % 4)
        try:
            return urlsafe_b64decode(padded.encode("ascii")).hex()
        except (ValueError, OSError) as error:
            raise CallbackDecodeError("invalid compressed session id") from error
    if prefix == "p":
        return raw
    raise CallbackDecodeError("unknown session token")


def _join(*parts: str) -> str:
    return _SEPARATOR.join(parts)


def _field(value: str) -> str:
    if not value or _SEPARATOR in value:
        raise CallbackDecodeError("callback field is empty or contains a delimiter")
    return value


def _encode_value(value: ChoiceValue) -> tuple[str]:
    if isinstance(value, bool) or not isinstance(value, int):
        return (f"s{_field(str(value))}",)
    return (f"i{value}",)


def _decode_value(token: str) -> ChoiceValue:
    if token.startswith("i"):
        try:
            return int(token[1:])
        except ValueError as error:
            raise CallbackDecodeError("invalid integer choice value") from error
    if token.startswith("s"):
        return token[1:]
    raise CallbackDecodeError("unknown choice value type")


def _parse_revision(raw: str) -> int:
    try:
        revision = int(raw)
    except ValueError as error:
        raise CallbackDecodeError("invalid revision") from error
    if revision < 0:
        raise CallbackDecodeError("invalid revision")
    return revision
