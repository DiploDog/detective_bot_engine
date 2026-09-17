from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from detective_bot.adapters.media import ResolvedMedia, sha256_file
from detective_bot.adapters.telegram.callback_data import (
    GameChoiceCallback,
    RequestRestartCallback,
    SelectGameCallback,
    unpack_callback,
)
from detective_bot.adapters.vk.callback_data import pack_payload
from detective_bot.adapters.vk.callback_data import (
    ChoicesPageCallback,
    unpack_payload,
)
from detective_bot.adapters.vk.inbound import (
    GENERIC_USER_ERROR,
    PRIVATE_CHAT_NOTICE,
    STALE_BUTTON_NOTICE,
)
from detective_bot.adapters.vk.renderer import VkMediaPolicy, VkRenderer
from detective_bot.application.models import ApplicationResult, GameActions
from detective_bot.engine.model import ChoiceActionOption, ChoicesAction, MediaAction
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from tests.fakes.telegram import MappingMediaResolver
from tests.fakes.vk import InMemoryVkMediaCache, RecordingVkSender
from tests.unit.vk.conftest import (
    NOW,
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


def keyboard_rows(sender: RecordingVkSender) -> list[list[str]]:
    keyboard = next(call.keyboard for call in reversed(sender.calls) if call.keyboard)
    return [
        [button["action"]["label"] for button in row]
        for row in json.loads(keyboard)["buttons"]
    ]


def first_payload(sender: RecordingVkSender, contained: str) -> dict:
    for call in sender.calls:
        for label, payload in keyboard_buttons(call.keyboard):
            if contained in label:
                return payload
    raise AssertionError(f"no button contains {contained!r}")


async def render_article_choices(vk_harness) -> None:
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
    definition = FileSystemGameCatalog(ROOT / "games").get(
        "killing_margo",
        "1.0.0",
    ).package.definition
    action = next(
        item
        for item in definition.scheduled_actions["reveal_articles"].actions
        if isinstance(item, ChoicesAction)
    )
    sender.calls.clear()
    await processor._renderer.render(
        PEER_ID,
        ApplicationResult(
            (GameActions(session_id="session-1", actions=(action,)),)
        ),
    )


async def test_start_opens_menu_without_creating_sessions(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message(text_message("начать"))
    rendered = texts(sender)
    labels = button_labels(sender)
    assert "Выберите расследование:" in rendered
    assert any("Убийство Марго" in text for text in labels)
    assert any("Дело Лоры Дейн" in text for text in labels)
    assert not any("Продолжить" in text for text in labels)
    assert not any("Начать заново" in text for text in labels)
    assert uow.sessions.sessions == {}


async def test_new_game_starts_without_restart_confirmation(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await processor.process_message(text_message("начать"))
    select_payload = first_payload(sender, "Дело Лоры Дейн")
    sender.calls.clear()

    await processor.process_message_event(
        callback_event(select_payload, event_id="2")
    )

    assert len(uow.sessions.sessions) == 1
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "lora_scene1"
    )
    assert not any("заново?" in text for text in texts(sender))


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
    labels = button_labels(sender)
    assert "Продолжить: Дело Лоры Дейн" in labels
    assert "Начать заново: Дело Лоры Дейн" in labels
    assert unpack_payload(first_payload(sender, "Продолжить")) == SelectGameCallback(
        "lora_dein"
    )
    assert unpack_payload(first_payload(sender, "Начать заново")) == (
        RequestRestartCallback("session-1")
    )


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
    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=3))
    restart_payload = first_payload(sender, "Начать заново")
    sender.calls.clear()
    await processor.process_message_event(
        callback_event(restart_payload, event_id="4")
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("заново" in text for text in texts(sender))

    cancel_payload = first_payload(sender, "Нет")
    sender.calls.clear()
    await processor.process_message_event(
        callback_event(cancel_payload, event_id="5")
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("отменён" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=6))
    continue_payload = first_payload(sender, "Продолжить")
    await processor.process_message_event(
        callback_event(continue_payload, event_id="7")
    )
    selected = await uow.sessions.get_selected(before.player_context)
    assert selected is not None
    assert selected.session_id == "session-1"
    assert selected.engine_snapshot == before.engine_snapshot

    sender.calls.clear()
    await processor.process_message(text_message("начать", message_id=8))
    restart_payload = first_payload(sender, "Начать заново")
    sender.calls.clear()
    await processor.process_message_event(
        callback_event(restart_payload, event_id="9")
    )
    confirm_payload = first_payload(sender, "Да")
    sender.calls.clear()
    await processor.process_message_event(
        callback_event(confirm_payload, event_id="10")
    )
    assert uow.sessions.sessions["session-1"].superseded_at is not None
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "lora_scene1"
    )
    assert any("УБИЙСТВО ЛОРЫ ДЕЙН" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_message_event(
        callback_event(confirm_payload, event_id="11")
    )
    assert len(uow.sessions.sessions) == 2
    selected = await uow.sessions.get_selected(before.player_context)
    assert selected is not None
    assert selected.session_id == "session-2"
    assert texts(sender) == [GENERIC_USER_ERROR]


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
    assert "Назад" not in button_labels(sender)
    assert "Далее" not in button_labels(sender)
    assert keyboard_rows(sender) == [["Да"], ["Нет"]]
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


async def test_oversized_choices_paginate_forward_and_back(vk_harness) -> None:
    processor, sender, _uow = vk_harness
    await render_article_choices(vk_harness)
    definition = FileSystemGameCatalog(ROOT / "games").get(
        "killing_margo",
        "1.0.0",
    ).package.definition
    action = next(
        item
        for item in definition.scheduled_actions["reveal_articles"].actions
        if isinstance(item, ChoicesAction)
    )
    first_labels = button_labels(sender)
    first_rows = keyboard_rows(sender)
    assert len(first_labels) == 6
    assert sum(label[:1].isdigit() for label in first_labels) == 5
    assert "Далее" in first_labels
    assert len(first_rows) == 6
    assert max(map(len, first_labels)) <= 40
    assert all(option.label in texts(sender)[0] for option in action.options[:5])
    next_payload = first_payload(sender, "Далее")
    assert unpack_payload(next_payload) == ChoicesPageCallback(
        "session-1",
        20,
        "read_article",
        1,
    )

    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="2"))
    second_labels = button_labels(sender)
    second_rows = keyboard_rows(sender)
    assert len(second_labels) == 7
    assert any(label.startswith("6.") for label in second_labels)
    assert any(label.startswith("10.") for label in second_labels)
    assert "Назад" in second_labels
    assert "Далее" in second_labels
    assert len(second_rows) == 6
    assert second_rows[-1] == ["Назад", "Далее"]
    assert max(map(len, second_labels)) <= 40
    assert all(option.label in texts(sender)[0] for option in action.options[5:10])

    next_payload = first_payload(sender, "Далее")
    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="3"))
    third_labels = button_labels(sender)
    third_rows = keyboard_rows(sender)
    assert len(third_labels) == 2
    assert any(label.startswith("11.") for label in third_labels)
    assert "Назад" in third_labels
    assert "Далее" not in third_labels
    assert len(third_rows) == 2
    assert max(map(len, third_labels)) <= 40
    assert action.options[10].label in texts(sender)[0]

    back_payload = first_payload(sender, "Назад")
    sender.calls.clear()
    await processor.process_message_event(callback_event(back_payload, event_id="4"))
    assert keyboard_rows(sender) == second_rows


async def test_long_choice_prefixes_keep_distinct_callback_values() -> None:
    sender = RecordingVkSender()
    renderer = VkRenderer(
        sender=sender,
        resolver=MappingMediaResolver({}),
        policy=VkMediaPolicy(),
    )
    common_prefix = "Одинаковое очень длинное начало варианта ответа "
    action = ChoicesAction(
        type="choices",
        interaction="long_choices",
        text="Выберите:",
        options=(
            ChoiceActionOption(value="first", label=f"{common_prefix}первый"),
            ChoiceActionOption(value="second", label=f"{common_prefix}второй"),
        ),
    )

    await renderer.render(
        PEER_ID,
        ApplicationResult(
            (GameActions(session_id="session-1", actions=(action,)),)
        ),
    )

    labels_and_payloads = keyboard_buttons(sender.calls[0].keyboard)
    assert [len(label) for label, _payload in labels_and_payloads] == [40, 40]
    callbacks = [unpack_payload(payload) for _label, payload in labels_and_payloads]
    assert [callback.value for callback in callbacks] == ["first", "second"]
    assert action.options[0].label in sender.calls[0].text
    assert action.options[1].label in sender.calls[0].text


async def test_choice_on_second_page_is_regular_semantic_input(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await render_article_choices(vk_harness)
    next_payload = first_payload(sender, "Далее")
    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="2"))
    article_payload = first_payload(sender, "9.")
    assert isinstance(unpack_payload(article_payload), GameChoiceCallback)

    sender.calls.clear()
    await processor.process_message_event(callback_event(article_payload, event_id="3"))
    assert any("Springfield FC" in text for text in texts(sender))
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == 20


async def test_choice_on_third_page_is_regular_semantic_input(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await render_article_choices(vk_harness)
    next_payload = first_payload(sender, "Далее")
    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="2"))
    next_payload = first_payload(sender, "Далее")
    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="3"))
    article_payload = first_payload(sender, "11.")
    assert isinstance(unpack_payload(article_payload), GameChoiceCallback)

    sender.calls.clear()
    await processor.process_message_event(callback_event(article_payload, event_id="4"))
    assert any("Cheesus Crust" in text for text in texts(sender))
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == 20


async def test_stale_pagination_callback_does_not_call_engine(vk_harness) -> None:
    processor, sender, uow = vk_harness
    await render_article_choices(vk_harness)
    next_payload = first_payload(sender, "Далее")
    session = uow.sessions.sessions["session-1"]
    uow.sessions.sessions["session-1"] = replace(
        session,
        engine_snapshot=session.engine_snapshot.model_copy(update={"revision": 21}),
    )

    sender.calls.clear()
    await processor.process_message_event(callback_event(next_payload, event_id="2"))
    assert texts(sender) == [STALE_BUTTON_NOTICE]
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == 21


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


async def test_vk_audio_uses_declared_platform_variant(vk_harness) -> None:
    processor, sender, _uow = vk_harness
    await processor.process_message_event(
        callback_event(pack_payload(SelectGameCallback("killing_margo")), event_id="1")
    )
    sender.calls.clear()

    await processor._renderer.render(
        PEER_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(MediaAction(type="media", asset="phone_recording"),),
                ),
            )
        ),
    )

    assert sender.calls[0].method == "audio"
    assert sender.calls[0].path == (
        ROOT / "games/killing_margo/1.0.0/assets/phone_recording_vk.ogg"
    )


async def test_vk_voice_cache_hit_skips_upload() -> None:
    audio = ROOT / "games/killing_margo/1.0.0/assets/phone_recording_vk.ogg"
    sender = RecordingVkSender()
    cache = InMemoryVkMediaCache()
    renderer = VkRenderer(
        sender=sender,
        resolver=MappingMediaResolver(
            {"voice": ResolvedMedia("voice", "audio", audio)}
        ),
        policy=VkMediaPolicy(),
        media_cache=cache,
        community_id="100",
    )
    result = ApplicationResult(
        (
            GameActions(
                session_id="session-1",
                actions=(MediaAction(type="media", asset="voice"),),
            ),
        )
    )

    await renderer.render(PEER_ID, result)
    sender.calls.clear()
    await renderer.render(PEER_ID, result)

    assert sender.calls[0].method == "audio"
    assert sender.calls[0].path is None
    assert sender.calls[0].file_id == "uploaded:audio:phone_recording_vk.ogg"


async def test_stale_vk_voice_cache_reuploads_without_using_document_kind() -> None:
    audio = ROOT / "games/killing_margo/1.0.0/assets/phone_recording_vk.ogg"
    digest = sha256_file(audio)
    sender = RecordingVkSender()
    sender.stale_file_ids.add("stale-voice")
    cache = InMemoryVkMediaCache()
    await cache.put("100", digest, "audio", "old-document", now=NOW)
    await cache.put("100", digest, "voice", "stale-voice", now=NOW)
    renderer = VkRenderer(
        sender=sender,
        resolver=MappingMediaResolver(
            {"voice": ResolvedMedia("voice", "audio", audio)}
        ),
        policy=VkMediaPolicy(),
        media_cache=cache,
        community_id="100",
    )

    await renderer.render(
        PEER_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(MediaAction(type="media", asset="voice"),),
                ),
            )
        ),
    )

    assert sender.calls[0].path == audio
    assert await cache.get("100", digest, "voice") == (
        "uploaded:audio:phone_recording_vk.ogg"
    )
    assert await cache.get("100", digest, "audio") == "old-document"
