from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TypeAlias

from pydantic import TypeAdapter

from detective_bot.application.models import (
    ApplicationOutput,
    DuplicateInteraction,
    GameActions,
    MenuEntryState,
    MenuGame,
    Notice,
    OutboundDelivery,
    OutboundDeliveryStatus,
    PlayerContext,
    ShowGameMenu,
    ShowRestartConfirmation,
    StaleInteraction,
)
from detective_bot.engine.model import (
    InputStatus,
    InvalidReason,
    OutputAction,
)

_OUTPUT_ACTION_ADAPTER = TypeAdapter(OutputAction)

OutboundSemantic: TypeAlias = (
    OutputAction | ShowGameMenu | ShowRestartConfirmation | Notice | StaleInteraction
)

_ENGINE_TYPES = frozenset({"text", "media", "choices"})


class OutboundSerializationError(ValueError):
    pass


def serialize_engine_action(action: OutputAction) -> dict:
    return action.model_dump(mode="json")


def serialize_application_output(output: ApplicationOutput) -> dict:
    if isinstance(output, ShowGameMenu):
        return {
            "type": "show_game_menu",
            "games": [
                {
                    "game_id": game.game_id,
                    "game_version": game.game_version,
                    "display_title": game.display_title,
                    "state": game.state.value,
                    "session_id": game.session_id,
                }
                for game in output.games
            ],
        }
    if isinstance(output, ShowRestartConfirmation):
        return {
            "type": "show_restart_confirmation",
            "session_id": output.session_id,
            "game_id": output.game_id,
            "display_title": output.display_title,
        }
    if isinstance(output, Notice):
        return {
            "type": "notice",
            "code": output.code,
            "text": output.text,
        }
    if isinstance(output, StaleInteraction):
        return {
            "type": "stale_interaction",
            "expected_session_id": output.expected_session_id,
            "selected_session_id": output.selected_session_id,
        }
    if isinstance(output, GameActions):
        return {
            "type": "game_actions",
            "session_id": output.session_id,
            "actions": [
                serialize_engine_action(action) for action in output.actions
            ],
            "outcome_id": output.outcome_id,
            "interaction_id": output.interaction_id,
            "input_status": output.input_status.value,
            "invalid_reason": (
                output.invalid_reason.value
                if output.invalid_reason is not None
                else None
            ),
        }
    if isinstance(output, DuplicateInteraction):
        raise OutboundSerializationError(
            "duplicate interactions are not outbound deliveries"
        )
    raise OutboundSerializationError(
        f"unsupported application output: {type(output).__name__}"
    )


def deserialize_action_payload(payload: Mapping[str, object]) -> OutboundSemantic:
    kind = payload.get("type")
    if kind in _ENGINE_TYPES:
        return _OUTPUT_ACTION_ADAPTER.validate_python(payload)
    if kind == "show_game_menu":
        return ShowGameMenu(
            games=tuple(
                MenuGame(
                    game_id=str(game["game_id"]),
                    game_version=str(game["game_version"]),
                    display_title=str(game["display_title"]),
                    state=MenuEntryState(str(game["state"])),
                    session_id=(
                        str(game["session_id"])
                        if game.get("session_id") is not None
                        else None
                    ),
                )
                for game in payload["games"]  # type: ignore[index]
            )
        )
    if kind == "show_restart_confirmation":
        return ShowRestartConfirmation(
            session_id=str(payload["session_id"]),
            game_id=str(payload["game_id"]),
            display_title=str(payload["display_title"]),
        )
    if kind == "notice":
        return Notice(code=str(payload["code"]), text=str(payload["text"]))
    if kind == "stale_interaction":
        selected = payload.get("selected_session_id")
        return StaleInteraction(
            expected_session_id=str(payload["expected_session_id"]),
            selected_session_id=str(selected) if selected is not None else None,
        )
    if kind == "game_actions":
        reason = payload.get("invalid_reason")
        return GameActions(
            session_id=str(payload["session_id"]),
            actions=tuple(
                _OUTPUT_ACTION_ADAPTER.validate_python(action)
                for action in payload["actions"]  # type: ignore[union-attr]
            ),
            outcome_id=(
                str(payload["outcome_id"])
                if payload.get("outcome_id") is not None
                else None
            ),
            interaction_id=(
                str(payload["interaction_id"])
                if payload.get("interaction_id") is not None
                else None
            ),
            input_status=InputStatus(str(payload["input_status"])),
            invalid_reason=(
                None if reason is None else InvalidReason(str(reason))
            ),
        )
    raise OutboundSerializationError(f"unknown outbound payload type: {kind!r}")


def iter_outbound_payloads(
    outputs: tuple[ApplicationOutput, ...],
) -> tuple[tuple[str | None, dict], ...]:
    items: list[tuple[str | None, dict]] = []
    for output in outputs:
        if isinstance(output, DuplicateInteraction):
            continue
        if isinstance(output, GameActions):
            if output.input_status is InputStatus.STALE:
                items.append(
                    (
                        output.session_id,
                        {
                            "type": "stale_interaction",
                            "expected_session_id": output.session_id,
                            "selected_session_id": output.session_id,
                        },
                    )
                )
                continue
            for action in output.actions:
                items.append((output.session_id, serialize_engine_action(action)))
            continue
        if isinstance(output, ShowRestartConfirmation):
            items.append((output.session_id, serialize_application_output(output)))
            continue
        if isinstance(output, StaleInteraction):
            items.append(
                (output.selected_session_id, serialize_application_output(output))
            )
            continue
        items.append((None, serialize_application_output(output)))
    return tuple(items)


def build_outbound_deliveries(
    player_context: PlayerContext,
    outputs: tuple[ApplicationOutput, ...],
    *,
    source_event_id: str | None,
    now: datetime,
) -> tuple[OutboundDelivery, ...]:
    return tuple(
        OutboundDelivery(
            player_context=player_context,
            session_id=session_id,
            source_event_id=source_event_id,
            sequence_no=index,
            action_payload=payload,
            status=OutboundDeliveryStatus.PENDING,
            due_at=now,
            created_at=now,
        )
        for index, (session_id, payload) in enumerate(iter_outbound_payloads(outputs))
    )
