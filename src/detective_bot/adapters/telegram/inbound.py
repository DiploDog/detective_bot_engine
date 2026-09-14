from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import CallbackQuery, Chat, Message, Update

from detective_bot.adapters.telegram.callback_data import (
    CallbackDecodeError,
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    LeaveToMenuCallback,
    OpenMenuCallback,
    RequestRestartCallback,
    SelectGameCallback,
    unpack_callback,
)
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


def map_update(update: Update) -> InboundResult:
    if update.callback_query is not None:
        return map_callback(update.callback_query, update)
    if update.message is not None:
        return map_message(update.message, update)
    return IgnoredUpdate()


def map_message(message: Message, update: Update) -> InboundResult:
    identity = _identity(message.chat, message.from_user)
    if isinstance(identity, RejectedUpdate):
        return identity
    if message.text is None:
        return IgnoredUpdate()
    command = _extract_command(message.text)
    event_id = external_event_id(update)
    if command == "/start":
        return IncomingInteraction(identity, OpenMenu(), event_id)
    if command == "/menu":
        return IncomingInteraction(identity, LeaveToMenu(), event_id)
    if command == "/restart":
        return RestartSelectedCommand(identity, event_id)
    if command is not None:
        return IgnoredUpdate()
    return IncomingInteraction(
        identity,
        SubmitGameInput(TextInput(text=message.text)),
        event_id,
    )


def map_callback(callback: CallbackQuery, update: Update) -> InboundResult:
    message = callback.message
    chat = message.chat if isinstance(message, Message) else None
    identity = _identity(chat, callback.from_user)
    if isinstance(identity, RejectedUpdate):
        return identity
    try:
        payload = unpack_callback(callback.data or "")
    except CallbackDecodeError:
        return RejectedUpdate("stale_callback", STALE_BUTTON_NOTICE)
    event_id = external_event_id(update)
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


def external_event_id(update: Update) -> str:
    return f"telegram:{update.update_id}"


def _identity(chat: Chat | None, user) -> PlayerContext | RejectedUpdate:
    if chat is None or user is None:
        return RejectedUpdate("missing_identity", GENERIC_USER_ERROR)
    if chat.type != "private":
        return RejectedUpdate("private_chat_required", PRIVATE_CHAT_NOTICE)
    return PlayerContext(
        platform=Platform.TELEGRAM,
        external_user_id=str(user.id),
        external_chat_id=str(chat.id),
    )


def _extract_command(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    token = text.split(maxsplit=1)[0]
    return token.split("@", 1)[0]
