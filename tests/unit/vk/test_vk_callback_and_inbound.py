from __future__ import annotations

from detective_bot.adapters.telegram.callback_data import (
    GameChoiceCallback,
    LeaveToMenuCallback,
    OpenMenuCallback,
    SelectGameCallback,
)
from detective_bot.adapters.vk.callback_data import (
    ChoicesPageCallback,
    pack_payload,
    unpack_payload,
)
from detective_bot.adapters.vk.inbound import (
    ChoicesPageRequest,
    PRIVATE_CHAT_NOTICE,
    RejectedUpdate,
    RestartSelectedCommand,
    map_message,
    map_message_event,
)
from detective_bot.application.models import LeaveToMenu, OpenMenu, Platform, SelectGame, SubmitGameInput
from detective_bot.engine.model import ChoiceInput, TextInput
from tests.unit.vk.conftest import callback_event, text_message


def test_payload_round_trip() -> None:
    payloads = (
        OpenMenuCallback(),
        LeaveToMenuCallback(),
        SelectGameCallback("example_game"),
        GameChoiceCallback("session-1", 4, "hint_q1", "yes"),
        GameChoiceCallback("session-1", 21, "read_article", 3),
        ChoicesPageCallback("session-1", 21, "read_article", 1),
    )
    for payload in payloads:
        packed = pack_payload(payload)
        assert unpack_payload(packed) == payload


def test_start_menu_restart_and_text_map_to_application_interactions() -> None:
    start = map_message(text_message("начать"))
    assert start.action == OpenMenu()
    assert start.player_context.platform is Platform.VK
    assert start.player_context.external_user_id == "22"
    assert start.external_event_id == "vk:message:1"

    menu = map_message(text_message("меню"))
    assert isinstance(menu.action, LeaveToMenu)

    restart = map_message(text_message("заново"))
    assert isinstance(restart, RestartSelectedCommand)

    slash = map_message(text_message("/start", message_id=4))
    assert slash.action == OpenMenu()

    answer = map_message(text_message("1,3", message_id=5))
    assert isinstance(answer.action, SubmitGameInput)
    assert answer.action.value == TextInput(text="1,3")


def test_callback_maps_to_select_and_choice_input() -> None:
    select = map_message_event(
        callback_event(pack_payload(SelectGameCallback("example_game")))
    )
    assert select.action == SelectGame("example_game")
    assert select.external_event_id == "vk:event:100"

    choice = map_message_event(
        callback_event(pack_payload(GameChoiceCallback("session-1", 2, "hint_q1", "yes")))
    )
    assert isinstance(choice.action, SubmitGameInput)
    assert choice.action.session_id == "session-1"
    assert choice.action.value == ChoiceInput(
        interaction_id="hint_q1",
        value="yes",
        session_revision=2,
    )

    page = map_message_event(
        callback_event(
            pack_payload(ChoicesPageCallback("session-1", 20, "read_article", 1))
        )
    )
    assert isinstance(page, ChoicesPageRequest)
    assert page.callback == ChoicesPageCallback(
        "session-1",
        20,
        "read_article",
        1,
    )


def test_group_chat_is_rejected_without_application_call() -> None:
    result = map_message(text_message("начать", peer_id=2_000_000_001, from_id=22))
    assert isinstance(result, RejectedUpdate)
    assert result.text == PRIVATE_CHAT_NOTICE


def test_malformed_callback_is_stale_notice() -> None:
    result = map_message_event(callback_event({"p": "not-a-valid-callback"}))
    assert isinstance(result, RejectedUpdate)
    assert "устарела" in result.text
