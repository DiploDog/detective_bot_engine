from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from detective_bot.adapters.media import ResolvedMedia
from detective_bot.adapters.telegram.callback_data import (
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    RequestRestartCallback,
    SelectGameCallback,
    unpack_callback,
)
from detective_bot.adapters.vk.callback_data import pack_payload
from detective_bot.adapters.vk.inbound import PRIVATE_CHAT_NOTICE, STALE_BUTTON_NOTICE
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.application.models import ApplicationResult, GameActions
from detective_bot.engine.model import MediaAction
from tests.fakes.telegram import MappingMediaResolver
from tests.fakes.vk import RecordingVkSender
from tests.unit.vk.conftest import (
    PEER_ID,
    callback_event,
    keyboard_buttons,
    text_message,
)


ROOT = Path(__file__).resolve().parents[3]


def texts(sender: RecordingVkSender) -> list[str]:
    return [call.text for call in sender.calls if call.text is not None]


def button_labels(sender: RecordingVkSender) -> list[str]:
    labels: list[str] = []
    for call in sender.calls:
        labels.extend(label for label, _payload in keyboard_buttons(call.keyboard))
    return labels


def first_payload(sender: RecordingVkSender, contained: str) -> dict:
    for call in sender.calls:
        for label, payload in keyboard_buttons(call.keyboard):
            if contained in label:
                return payload
    raise AssertionError(f"no button contains {contained!r}")


async def test_start_opens_menu_without_creating_sessions(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message(text_message("начать"))
    rendered = texts(sender)
    labels = button_labels(sender)
    assert "Выберите расследование:" in rendered
    assert any("Убийство Марго" in text for text in labels)
    assert any("Дело Лоры Дейн" in text for text in labels)
    assert uow.sessions.sessions == {}


async def test_start_preserves_existing_progress(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("lora_dein")), event_id="1")
    )
    await processor.process_message(text_message("1,3", message_id=2))
    before = uow.sessions.sessions["session-1"]
    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=3))
    after = uow.sessions.sessions["session-1"]
    assert after.engine_snapshot.current_scene == "lora_scene2"
    assert after.engine_snapshot == before.engine_snapshot
    assert any("Продолжить: Дело Лоры Дейн" in label for label in button_labels(sender))


async def test_select_both_games_and_text_answer(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message(text_message("начать", message_id=1))
    await processor.process_message_event(
        callback_event(first_payload(sender, "Дело Лоры Дейн"), event_id="2")
    )
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "lora_scene1"
    )
    assert any("УБИЙСТВО ЛОРЫ ДЕЙН" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=3))
    await processor.process_message_event(
        callback_event(first_payload(sender, "Убийство Марго"), event_id="4")
    )
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "margo_q1_initial"
    )
    assert any("Том Митчел" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=5))
    await processor.process_message_event(
        callback_event(first_payload(sender, "Дело Лоры Дейн"), event_id="6")
    )
    sender.calls.clear()
    await processor.process_message(text_message("1,3", message_id=7))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "lora_scene2"
    )
    assert sender.calls


async def test_switch_games_preserves_progress(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="1")
    )
    await processor.process_message(text_message("нет", message_id=2))
    await processor.process_message(text_message("начать", message_id=3))
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("lora_dein")), event_id="4")
    )
    await processor.process_message(text_message("1,3", message_id=5))
    await processor.process_message(text_message("начать", message_id=6))
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="7")
    )
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == "margo_q2"
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "lora_scene2"
    )
    selected = await uow.sessions.get_selected(
        uow.sessions.sessions["session-1"].player_context
    )
    assert selected is not None
    assert selected.session_id == "session-1"


async def test_restart_request_confirm_and_cancel(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("lora_dein")), event_id="1")
    )
    await processor.process_message(text_message("1,3", message_id=2))
    before = uow.sessions.sessions["session-1"]
    await processor.process_message_event(
        callback_event(pack_payload(RequestRestartCallback("session-1")), event_id="3")
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("заново" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_message_event(
        callback_event(pack_payload(CancelRestartCallback("session-1")), event_id="4")
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("отменён" in text for text in texts(sender))

    await processor.process_message_event(
        callback_event(pack_payload(ConfirmRestartCallback("session-1")), event_id="5")
    )
    assert uow.sessions.sessions["session-1"].superseded_at is not None
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "lora_scene1"
    )


async def test_hint_choice_uses_generic_callback(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="1")
    )
    sender.calls.clear()
    await processor.process_message(text_message("да", message_id=2))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_q1_hint"
    )
    yes = first_payload(sender, "Да")
    payload = unpack_callback(yes["p"])
    assert isinstance(payload, GameChoiceCallback)
    sender.calls.clear()
    await processor.process_message_event(callback_event(yes, event_id="3"))
    rendered = "\n".join(texts(sender))
    assert "судмедэкспертизой" in rendered
    assert "наследил ботинками" in rendered
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_q1"
    )


async def test_article_choice_renders_article_text(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="1")
    )
    session = uow.sessions.sessions["session-1"]
    uow.sessions.sessions["session-1"] = replace(
        session,
        engine_snapshot=session.engine_snapshot.model_copy(
            update={"current_scene": "margo_articles", "revision": 20}
        ),
    )
    await processor.process_message_event(
        callback_event(
            pack_payload(GameChoiceCallback("session-1", 20, "read_article", 1)),
            event_id="2",
        )
    )
    assert any("клиник" in (text or "").lower() for text in texts(sender))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_articles"
    )


async def test_stale_game_callback_does_not_mutate(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="1")
    )
    await processor.process_message(text_message("да", message_id=2))
    revision = uow.sessions.sessions["session-1"].engine_snapshot.revision
    sender.calls.clear()
    await processor.process_message_event(
        callback_event(
            pack_payload(GameChoiceCallback("session-1", 1, "hint_q1", "yes")),
            event_id="3",
        )
    )
    assert STALE_BUTTON_NOTICE in texts(sender)
    assert (
        uow.sessions.sessions["session-1"].engine_snapshot.current_scene
        == "margo_q1_hint"
    )
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == revision


async def test_private_chat_restriction(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message(
        text_message("начать", peer_id=2_000_000_001, from_id=22)
    )
    assert texts(sender) == [PRIVATE_CHAT_NOTICE]
    assert uow.sessions.sessions == {}


async def test_duplicate_message_id_does_not_mutate_twice(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("lora_dein")), event_id="1")
    )
    await processor.process_message(text_message("1,3", message_id=2))
    revision = uow.sessions.sessions["session-1"].engine_snapshot.revision
    sender.calls.clear()
    await processor.process_message(text_message("1,3", message_id=2))
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == revision
    assert sender.calls == []


async def test_media_methods_follow_type_and_vk_photo_report_policy() -> None:
    sender = RecordingVkSender()
    image = ROOT / "games/killing_margo/1.0.0/assets/safe_closed.jpg"
    audio = ROOT / "games/killing_margo/1.0.0/assets/phone_recording.mp3"
    report = ROOT / "games/killing_margo/1.0.0/assets/final_police_report.jpg"
    renderer = VkRenderer(
        sender=sender,
        resolver=MappingMediaResolver(
            {
                "closed": ResolvedMedia("closed", "image", image),
                "voice": ResolvedMedia("voice", "audio", audio),
                "final_police_report": ResolvedMedia(
                    "final_police_report",
                    "image",
                    report,
                ),
            }
        ),
        policy=VkMediaPolicy(),
    )
    await renderer.render(
        PEER_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(
                        MediaAction(type="media", asset="closed", caption="closed"),
                        MediaAction(type="media", asset="voice", caption="voice"),
                        MediaAction(
                            type="media",
                            asset="final_police_report",
                            caption="report",
                        ),
                    ),
                ),
            )
        ),
    )
    assert [call.method for call in sender.calls] == ["photo", "audio", "photo"]
    assert sender.calls[0].path == image
    assert sender.calls[1].path == audio
    assert sender.calls[2].path == report
