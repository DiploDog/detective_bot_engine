from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from aiogram import Bot, Dispatcher

from detective_bot.adapters.telegram.callback_data import (
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    RequestRestartCallback,
    SelectGameCallback,
    pack_callback,
    unpack_callback,
)
from detective_bot.adapters.telegram.handlers import create_router
from detective_bot.adapters.telegram.inbound import PRIVATE_CHAT_NOTICE, STALE_BUTTON_NOTICE
from detective_bot.adapters.telegram.media import ResolvedMedia
from detective_bot.adapters.telegram.renderer import (
    TelegramMediaPolicy,
    TelegramRenderer,
)
from detective_bot.application.models import ApplicationResult, GameActions, Platform
from detective_bot.engine.model import MediaAction
from tests.fakes.telegram import MappingMediaResolver, RecordingTelegramSender
from tests.unit.telegram.conftest import CHAT_ID, callback_update, text_update


ROOT = Path(__file__).resolve().parents[3]


def texts(sender: RecordingTelegramSender) -> list[str]:
    return [call.text for call in sender.calls if call.text is not None]


def button_labels(sender: RecordingTelegramSender) -> list[str]:
    labels: list[str] = []
    for call in sender.calls:
        if call.reply_markup is None:
            continue
        for row in call.reply_markup.inline_keyboard:
            labels.extend(button.text for button in row)
    return labels


def first_callback(sender: RecordingTelegramSender, contained: str) -> str:
    for call in sender.calls:
        if call.reply_markup is None:
            continue
        for row in call.reply_markup.inline_keyboard:
            for button in row:
                if contained in button.text:
                    return button.callback_data
    raise AssertionError(f"no button contains {contained!r}")


async def test_start_opens_menu_without_creating_sessions(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(text_update("/start"))
    rendered = texts(sender)
    labels = button_labels(sender)
    assert "Выберите расследование:" in rendered
    assert any("Убийство Марго" in text for text in labels)
    assert any("Дело Лоры Дейн" in text for text in labels)
    assert uow.sessions.sessions == {}


async def test_aiogram_router_injects_event_update(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    bot = Bot("1:TEST")
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(processor))
    try:
        await dispatcher.feed_update(bot, text_update("/start"))
    finally:
        await bot.session.close()
    assert "Выберите расследование:" in texts(sender)
    assert uow.sessions.sessions == {}


async def test_start_preserves_existing_progress(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=1)
    )
    await processor.process_update(text_update("1,3", update_id=2))
    before = uow.sessions.sessions["session-1"]
    sender.calls.clear()
    await processor.process_update(text_update("/start", update_id=3))
    after = uow.sessions.sessions["session-1"]
    assert after.engine_snapshot.current_scene == "lora_scene2"
    assert after.engine_snapshot == before.engine_snapshot
    assert any("Продолжить: Дело Лоры Дейн" in label for label in button_labels(sender))


async def test_select_both_games_and_text_answer(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(text_update("/start", update_id=1))
    await processor.process_update(
        callback_update(first_callback(sender, "Дело Лоры Дейн"), update_id=2)
    )
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "lora_scene1"
    )
    assert any("УБИЙСТВО ЛОРЫ ДЕЙН" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_update(text_update("/start", update_id=3))
    await processor.process_update(
        callback_update(first_callback(sender, "Убийство Марго"), update_id=4)
    )
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "margo_q1_initial"
    )
    assert any("Том Митчел" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_update(text_update("/start", update_id=5))
    await processor.process_update(
        callback_update(first_callback(sender, "Дело Лоры Дейн"), update_id=6)
    )
    sender.calls.clear()
    await processor.process_update(text_update("1,3", update_id=7))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "lora_scene2"
    )
    assert sender.calls


async def test_switch_games_preserves_progress(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("killing_margo")), update_id=1)
    )
    await processor.process_update(text_update("нет", update_id=2))
    await processor.process_update(text_update("/start", update_id=3))
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=4)
    )
    await processor.process_update(text_update("1,3", update_id=5))
    await processor.process_update(text_update("/start", update_id=6))
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("killing_margo")), update_id=7)
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


async def test_restart_request_confirm_and_cancel(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=1)
    )
    await processor.process_update(text_update("1,3", update_id=2))
    before = uow.sessions.sessions["session-1"]
    await processor.process_update(
        callback_update(pack_callback(RequestRestartCallback("session-1")), update_id=3)
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("заново" in text for text in texts(sender))

    sender.calls.clear()
    await processor.process_update(
        callback_update(pack_callback(CancelRestartCallback("session-1")), update_id=4)
    )
    assert uow.sessions.sessions["session-1"] == before
    assert any("отменён" in text for text in texts(sender))

    await processor.process_update(
        callback_update(pack_callback(ConfirmRestartCallback("session-1")), update_id=5)
    )
    assert uow.sessions.sessions["session-1"].superseded_at is not None
    assert uow.sessions.sessions["session-2"].engine_snapshot.current_scene == (
        "lora_scene1"
    )


async def test_hint_choice_uses_generic_inline_callback(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("killing_margo")), update_id=1)
    )
    sender.calls.clear()
    await processor.process_update(text_update("да", update_id=2))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_q1_hint"
    )
    yes = first_callback(sender, "Да")
    payload = unpack_callback(yes)
    assert isinstance(payload, GameChoiceCallback)
    sender.calls.clear()
    await processor.process_update(callback_update(yes, update_id=3))
    rendered = "\n".join(texts(sender))
    assert "судмедэкспертизой" in rendered
    assert "наследил ботинками" in rendered
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_q1"
    )


async def test_article_choice_renders_article_text(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("killing_margo")), update_id=1)
    )
    session = uow.sessions.sessions["session-1"]
    uow.sessions.sessions["session-1"] = replace(
        session,
        engine_snapshot=session.engine_snapshot.model_copy(
            update={"current_scene": "margo_articles", "revision": 20}
        ),
    )
    await processor.process_update(
        callback_update(
            pack_callback(
                GameChoiceCallback("session-1", 20, "read_article", 1)
            ),
            update_id=2,
        )
    )
    assert any("клиник" in (text or "").lower() for text in texts(sender))
    assert uow.sessions.sessions["session-1"].engine_snapshot.current_scene == (
        "margo_articles"
    )


async def test_stale_game_callback_does_not_mutate(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("killing_margo")), update_id=1)
    )
    await processor.process_update(text_update("да", update_id=2))
    revision = uow.sessions.sessions["session-1"].engine_snapshot.revision
    sender.calls.clear()
    await processor.process_update(
        callback_update(
            pack_callback(GameChoiceCallback("session-1", 1, "hint_q1", "yes")),
            update_id=3,
        )
    )
    assert STALE_BUTTON_NOTICE in texts(sender)
    assert (
        uow.sessions.sessions["session-1"].engine_snapshot.current_scene
        == "margo_q1_hint"
    )
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == revision


async def test_private_chat_restriction(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(text_update("/start", chat_type="group"))
    assert texts(sender) == [PRIVATE_CHAT_NOTICE]
    assert uow.sessions.sessions == {}


async def test_duplicate_update_id_does_not_mutate_twice(telegram_harness) -> None:
    processor, sender, uow = telegram_harness
    await processor.process_update(
        callback_update(pack_callback(SelectGameCallback("lora_dein")), update_id=1)
    )
    await processor.process_update(text_update("1,3", update_id=2))
    revision = uow.sessions.sessions["session-1"].engine_snapshot.revision
    sender.calls.clear()
    await processor.process_update(text_update("1,3", update_id=2))
    assert uow.sessions.sessions["session-1"].engine_snapshot.revision == revision
    assert sender.calls == []


async def test_media_methods_follow_type_and_document_policy() -> None:
    sender = RecordingTelegramSender()
    image = ROOT / "games/killing_margo/1.0.0/assets/safe_closed.jpg"
    audio = ROOT / "games/killing_margo/1.0.0/assets/phone_recording.mp3"
    report = ROOT / "games/killing_margo/1.0.0/assets/final_police_report.jpg"
    renderer = TelegramRenderer(
        sender=sender,
        resolver=MappingMediaResolver(
            {
                "closed": ResolvedMedia("closed", "image", image),
                "voice": ResolvedMedia("voice", "audio", audio),
                "report_asset": ResolvedMedia("report_asset", "image", report),
            }
        ),
        policy=TelegramMediaPolicy(document_asset_ids=frozenset({"report_asset"})),
    )
    await renderer.render(
        CHAT_ID,
        ApplicationResult(
            (
                GameActions(
                    session_id="session-1",
                    actions=(
                        MediaAction(type="media", asset="closed", caption="closed"),
                        MediaAction(type="media", asset="voice", caption="voice"),
                        MediaAction(
                            type="media",
                            asset="report_asset",
                            caption="report",
                        ),
                    ),
                ),
            )
        ),
    )
    assert [call.method for call in sender.calls] == ["photo", "audio", "document"]
    assert sender.calls[0].path == image
    assert sender.calls[1].path == audio
    assert sender.calls[2].path == report
