from __future__ import annotations

from detective_bot.adapters.telegram.callback_data import (
    CALLBACK_DATA_LIMIT,
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    LeaveToMenuCallback,
    OpenMenuCallback,
    RequestRestartCallback,
    SelectGameCallback,
    pack_callback,
    unpack_callback,
)
from detective_bot.adapters.telegram.inbound import (
    PRIVATE_CHAT_NOTICE,
    RejectedUpdate,
    RestartSelectedCommand,
    map_update,
)
from detective_bot.application.models import (
    LeaveToMenu,
    OpenMenu,
    Platform,
    SelectGame,
    SubmitGameInput,
)
from detective_bot.engine.model import ChoiceInput, TextInput
from tests.unit.telegram.conftest import callback_update, text_update


def test_callback_round_trip_for_application_and_game_actions() -> None:
    payloads = (
        OpenMenuCallback(),
        LeaveToMenuCallback(),
        SelectGameCallback("example_game"),
        RequestRestartCallback("session-1"),
        ConfirmRestartCallback("session-1"),
        CancelRestartCallback("session-1"),
        GameChoiceCallback("session-1", 4, "hint_q1", "yes"),
        GameChoiceCallback("session-1", 21, "read_article", 3),
        GameChoiceCallback("a" * 32, 12, "read_article", 11),
    )
    for payload in payloads:
        packed = pack_callback(payload)
        assert len(packed.encode("utf-8")) <= CALLBACK_DATA_LIMIT
        assert unpack_callback(packed) == payload


def test_start_and_text_map_to_application_interactions() -> None:
    start = map_update(text_update("/start"))
    assert start.action == OpenMenu()
    assert start.player_context.platform is Platform.TELEGRAM
    assert start.player_context.external_user_id == "11"
    assert start.external_event_id == "telegram:1"

    menu = map_update(text_update("/menu"))
    assert isinstance(menu.action, LeaveToMenu)

    restart = map_update(text_update("/restart"))
    assert isinstance(restart, RestartSelectedCommand)

    answer = map_update(text_update("1,3"))
    assert isinstance(answer.action, SubmitGameInput)
    assert answer.action.value == TextInput(text="1,3")


def test_callback_maps_to_select_and_choice_input() -> None:
    select = map_update(
        callback_update(pack_callback(SelectGameCallback("example_game")))
    )
    assert select.action == SelectGame("example_game")

    choice = map_update(
        callback_update(
            pack_callback(GameChoiceCallback("session-1", 2, "hint_q1", "yes"))
        )
    )
    assert isinstance(choice.action, SubmitGameInput)
    assert choice.action.session_id == "session-1"
    assert choice.action.value == ChoiceInput(
        interaction_id="hint_q1",
        value="yes",
        session_revision=2,
    )


def test_group_chat_is_rejected_without_application_call() -> None:
    result = map_update(text_update("/start", chat_type="group"))
    assert isinstance(result, RejectedUpdate)
    assert result.text == PRIVATE_CHAT_NOTICE


def test_malformed_callback_is_stale_notice() -> None:
    result = map_update(callback_update("not-a-valid-callback"))
    assert isinstance(result, RejectedUpdate)
    assert "устарела" in result.text
