from __future__ import annotations

from datetime import UTC, datetime

import pytest

from detective_bot.application.models import (
    DuplicateInteraction,
    GameActions,
    MenuEntryState,
    MenuGame,
    Notice,
    OutboundDeliveryStatus,
    Platform,
    PlayerContext,
    ShowGameMenu,
    ShowRestartConfirmation,
    StaleInteraction,
)
from detective_bot.application.outbound import (
    OutboundSerializationError,
    build_outbound_deliveries,
    deserialize_action_payload,
    serialize_application_output,
    serialize_engine_action,
)
from detective_bot.engine.model import (
    ChoiceActionOption,
    ChoicesAction,
    InputStatus,
    MediaAction,
    TextAction,
)


PLAYER = PlayerContext(Platform.TELEGRAM, "user-1", "chat-1")
NOW = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)


def test_engine_actions_round_trip() -> None:
    text = TextAction(type="text", text="Привет")
    media = MediaAction(type="media", asset="phone_recording", caption="аудио")
    choices = ChoicesAction(
        type="choices",
        interaction="hint_q1",
        text="Подсказка?",
        options=(
            ChoiceActionOption(value="yes", label="Да"),
            ChoiceActionOption(value="no", label="Нет"),
        ),
    )
    for action in (text, media, choices):
        payload = serialize_engine_action(action)
        assert payload["type"] in {"text", "media", "choices"}
        assert deserialize_action_payload(payload) == action


def test_application_menu_and_notice_round_trip() -> None:
    menu = ShowGameMenu(
        (
            MenuGame(
                game_id="lora_dein",
                game_version="1.0.0",
                display_title="Лора Дейн",
                state=MenuEntryState.CONTINUE,
                session_id="session-1",
            ),
            MenuGame(
                game_id="killing_margo",
                game_version="1.0.0",
                display_title="Убийство Марго",
                state=MenuEntryState.NEW,
            ),
        )
    )
    notice = Notice("left_to_menu", "Прогресс сохранён.")
    confirmation = ShowRestartConfirmation(
        session_id="session-1",
        game_id="lora_dein",
        display_title="Лора Дейн",
    )
    stale = StaleInteraction("session-1", "session-2")
    for output in (menu, notice, confirmation, stale):
        payload = serialize_application_output(output)
        assert "type" in payload
        assert deserialize_action_payload(payload) == output


def test_game_actions_are_flattened_with_sequence_numbers() -> None:
    outputs = (
        GameActions(
            session_id="session-1",
            actions=(
                TextAction(type="text", text="один"),
                TextAction(type="text", text="два"),
                MediaAction(type="media", asset="safe_closed"),
            ),
        ),
    )
    deliveries = build_outbound_deliveries(
        PLAYER,
        outputs,
        source_event_id="event-1",
        now=NOW,
    )
    assert [item.sequence_no for item in deliveries] == [0, 1, 2]
    assert [item.action_payload["type"] for item in deliveries] == [
        "text",
        "text",
        "media",
    ]
    assert all(item.session_id == "session-1" for item in deliveries)
    assert all(item.status is OutboundDeliveryStatus.PENDING for item in deliveries)
    assert all(item.source_event_id == "event-1" for item in deliveries)
    restored = tuple(
        deserialize_action_payload(item.action_payload) for item in deliveries
    )
    assert restored == outputs[0].actions


def test_duplicate_interaction_is_not_enqueued() -> None:
    deliveries = build_outbound_deliveries(
        PLAYER,
        (DuplicateInteraction("event-1"),),
        source_event_id="event-1",
        now=NOW,
    )
    assert deliveries == ()


def test_unknown_payload_type_is_rejected() -> None:
    with pytest.raises(OutboundSerializationError, match="unknown outbound payload"):
        deserialize_action_payload({"type": "inline_keyboard"})


def test_stale_game_actions_become_stale_payload() -> None:
    deliveries = build_outbound_deliveries(
        PLAYER,
        (
            GameActions(
                session_id="session-1",
                actions=(),
                input_status=InputStatus.STALE,
            ),
        ),
        source_event_id="stale-1",
        now=NOW,
    )
    assert len(deliveries) == 1
    assert deliveries[0].action_payload["type"] == "stale_interaction"
    assert deserialize_action_payload(deliveries[0].action_payload) == StaleInteraction(
        "session-1",
        "session-1",
    )
