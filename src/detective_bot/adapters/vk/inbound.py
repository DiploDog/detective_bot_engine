from __future__ import annotations

from dataclasses import dataclass

from vkbottle.bot import Message, MessageEvent

from detective_bot.adapters.telegram.callback_data import (
    CallbackDecodeError,
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    LeaveToMenuCallback,
    OpenMenuCallback,
    RequestRestartCallback,
    SelectGameCallback,
)
from detective_bot.adapters.vk.callback_data import unpack_payload
from detective_bot.application.models import (
    CancelRestart,
    ConfirmRestart,
    IncomingInteraction,
    LeaveToMenu,
    OpenMenu,
    Platform,
    PlayerContext,
    RequestRestart,
    SelectGame,
    SubmitGameInput,
)
from detective_bot.engine.model import ChoiceInput, TextInput


PRIVATE_CHAT_NOTICE = "Игра доступна только в личном чате."
STALE_BUTTON_NOTICE = (
    "Эта кнопка уже устарела. Используйте актуальное сообщение."
)
GENERIC_USER_ERROR = "Не удалось обработать запрос. Попробуйте ещё раз."

_OPEN_MENU = frozenset({"начать", "start", "/start"})
_LEAVE_MENU = frozenset({"меню", "menu", "/menu"})
_RESTART = frozenset({"заново", "restart", "/restart"})


@dataclass(frozen=True, slots=True)
class RejectedUpdate:
    reason: str
    text: str


@dataclass(frozen=True, slots=True)
class RestartSelectedCommand:
    player_context: PlayerContext
    external_event_id: str


@dataclass(frozen=True, slots=True)
class IgnoredUpdate:
    pass


InboundResult = IncomingInteraction | RejectedUpdate | RestartSelectedCommand | IgnoredUpdate


def map_message(message: Message) -> InboundResult:
    identity = _identity(message.peer_id, message.from_id)
    if isinstance(identity, RejectedUpdate):
        return identity
    text = (message.text or "").strip()
    if not text:
        return IgnoredUpdate()
    command = _extract_command(text)
    event_id = message_event_id(message)
    if command in _OPEN_MENU:
        return IncomingInteraction(identity, OpenMenu(), event_id)
    if command in _LEAVE_MENU:
        return IncomingInteraction(identity, LeaveToMenu(), event_id)
    if command in _RESTART:
        return RestartSelectedCommand(identity, event_id)
    return IncomingInteraction(
        identity,
        SubmitGameInput(TextInput(text=text)),
        event_id,
    )


def map_message_event(event: MessageEvent) -> InboundResult:
    identity = _identity(event.peer_id, event.user_id)
    if isinstance(identity, RejectedUpdate):
        return identity
    try:
        payload = unpack_payload(event.payload)
    except CallbackDecodeError:
        return RejectedUpdate("stale_callback", STALE_BUTTON_NOTICE)
    event_id = callback_event_id(event)
    if isinstance(payload, OpenMenuCallback):
        return IncomingInteraction(identity, OpenMenu(), event_id)
    if isinstance(payload, LeaveToMenuCallback):
        return IncomingInteraction(identity, LeaveToMenu(), event_id)
    if isinstance(payload, SelectGameCallback):
        return IncomingInteraction(identity, SelectGame(payload.game_id), event_id)
    if isinstance(payload, RequestRestartCallback):
        return IncomingInteraction(
            identity,
            RequestRestart(payload.session_id),
            event_id,
        )
    if isinstance(payload, ConfirmRestartCallback):
        return IncomingInteraction(
            identity,
            ConfirmRestart(payload.session_id),
            event_id,
        )
    if isinstance(payload, CancelRestartCallback):
        return IncomingInteraction(
            identity,
            CancelRestart(payload.session_id),
            event_id,
        )
    if isinstance(payload, GameChoiceCallback):
        return IncomingInteraction(
            identity,
            SubmitGameInput(
                ChoiceInput(
                    interaction_id=payload.interaction_id,
                    value=payload.value,
                    session_revision=payload.revision,
                ),
                session_id=payload.session_id,
            ),
            event_id,
        )
    return RejectedUpdate("stale_callback", STALE_BUTTON_NOTICE)


def message_event_id(message: Message) -> str:
    return f"vk:message:{message.id}"


def callback_event_id(event: MessageEvent) -> str:
    return f"vk:event:{event.event_id}"


def _identity(peer_id: int, user_id: int) -> PlayerContext | RejectedUpdate:
    if peer_id != user_id:
        return RejectedUpdate("private_chat_required", PRIVATE_CHAT_NOTICE)
    return PlayerContext(
        platform=Platform.VK,
        external_user_id=str(user_id),
        external_chat_id=str(peer_id),
    )


def _extract_command(text: str) -> str:
    token = text.split(maxsplit=1)[0]
    return token.casefold()
