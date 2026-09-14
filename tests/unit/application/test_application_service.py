from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Coroutine, TypeVar

import pytest

from detective_bot.application.models import (
    ApplicationSessionStatus,
    CancelRestart,
    ConfirmRestart,
    DuplicateInteraction,
    GameActions,
    IncomingInteraction,
    MenuEntryState,
    Notice,
    OpenMenu,
    Platform,
    PlayerContext,
    RequestRestart,
    SelectGame,
    ShowGameMenu,
    ShowRestartConfirmation,
    StaleInteraction,
    SubmitGameInput,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.application.service import (
    ApplicationService,
    GameVersionUnavailable,
)
from detective_bot.engine.model import (
    ChoiceInput,
    InputStatus,
    InvalidReason,
    MediaAction,
    SessionStatus,
    TextAction,
    TextInput,
)
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from tests.fakes import (
    InMemoryProcessedEventRepository,
    InMemoryScheduledActionRepository,
    InMemorySessionRepository,
    InMemoryUnitOfWorkFactory,
)


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
T = TypeVar("T")


def run(coroutine: Coroutine[object, object, T]) -> T:
    return asyncio.run(coroutine)


@dataclass(slots=True)
class Harness:
    service: ApplicationService
    sessions: InMemorySessionRepository
    scheduled: InMemoryScheduledActionRepository
    processed: InMemoryProcessedEventRepository


def make_harness() -> Harness:
    uow_factory = InMemoryUnitOfWorkFactory()
    sequence = count(1)
    service = ApplicationService(
        catalog=FileSystemGameCatalog(ROOT / "games"),
        uow_factory=uow_factory,
        engine=GameEngine(),
        clock=lambda: NOW,
        session_id_factory=lambda: f"session-{next(sequence)}",
    )
    return Harness(
        service,
        uow_factory.sessions,
        uow_factory.scheduled_actions,
        uow_factory.processed_events,
    )


PLAYER = PlayerContext(
    platform=Platform.TELEGRAM,
    external_user_id="user-1",
    external_chat_id="chat-1",
)


async def send(
    harness: Harness,
    action: object,
    *,
    event_id: str | None = None,
):
    return await harness.service.handle(
        IncomingInteraction(
            player_context=PLAYER,
            action=action,  # type: ignore[arg-type]
            external_event_id=event_id,
        )
    )


def test_open_menu_lists_real_manifests_without_creating_sessions() -> None:
    async def scenario() -> None:
        harness = make_harness()

        result = await send(harness, OpenMenu())

        menu = result.outputs[0]
        assert isinstance(menu, ShowGameMenu)
        assert {
            item.game_id: (item.display_title, item.state)
            for item in menu.games
        } == {
            "killing_margo": ("Убийство Марго", MenuEntryState.NEW),
            "lora_dein": ("Дело Лоры Дейн", MenuEntryState.NEW),
        }
        assert harness.sessions.sessions == {}
        assert await harness.sessions.get_selected(PLAYER) is None

    run(scenario())


def test_open_menu_preserves_existing_progress() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))
        before = harness.sessions.sessions["session-1"]

        result = await send(harness, OpenMenu())

        after = harness.sessions.sessions["session-1"]
        assert after == before
        assert after.engine_snapshot.current_scene == "lora_scene2"
        assert await harness.sessions.get_selected(PLAYER) is None
        menu = result.outputs[0]
        assert isinstance(menu, ShowGameMenu)
        lora = next(item for item in menu.games if item.game_id == "lora_dein")
        assert lora.state is MenuEntryState.CONTINUE

    run(scenario())


def test_select_new_lora_starts_real_package_and_selects_session() -> None:
    async def scenario() -> None:
        harness = make_harness()

        result = await send(harness, SelectGame("lora_dein"))

        output = result.outputs[0]
        assert isinstance(output, GameActions)
        assert len(output.actions) == 1
        assert isinstance(output.actions[0], TextAction)
        assert "УБИЙСТВО ЛОРЫ ДЕЙН" in output.actions[0].text
        session = harness.sessions.sessions["session-1"]
        assert session.game_version == "1.0.0"
        assert session.engine_snapshot.current_scene == "lora_scene1"
        assert session.engine_snapshot.revision == 1
        assert await harness.sessions.get_selected(PLAYER) == session

    run(scenario())


def test_select_lora_again_resumes_without_restarting_scene() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))
        await send(harness, OpenMenu())

        result = await send(harness, SelectGame("lora_dein"))

        assert len(harness.sessions.created_ids) == 1
        session = harness.sessions.sessions["session-1"]
        assert session.engine_snapshot.current_scene == "lora_scene2"
        assert session.engine_snapshot.revision == 2
        assert await harness.sessions.get_selected(PLAYER) == session
        notice = result.outputs[0]
        assert isinstance(notice, Notice)
        assert notice.code == "session_resumed"

    run(scenario())


def test_select_margo_starts_real_entry_scene() -> None:
    async def scenario() -> None:
        harness = make_harness()

        result = await send(harness, SelectGame("killing_margo"))

        output = result.outputs[0]
        assert isinstance(output, GameActions)
        assert isinstance(output.actions[0], TextAction)
        assert "Меня зовут Том Митчел" in output.actions[0].text
        session = harness.sessions.sessions["session-1"]
        assert session.engine_snapshot.current_scene == "margo_q1_initial"

    run(scenario())


def test_switching_games_preserves_both_progress_snapshots() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("killing_margo"))
        await send(harness, SubmitGameInput(TextInput(text="нет")))
        await send(harness, OpenMenu())
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))
        await send(harness, OpenMenu())

        await send(harness, SelectGame("killing_margo"))

        margo = harness.sessions.sessions["session-1"]
        lora = harness.sessions.sessions["session-2"]
        assert margo.engine_snapshot.current_scene == "margo_q2"
        assert lora.engine_snapshot.current_scene == "lora_scene2"
        assert await harness.sessions.get_selected(PLAYER) == margo

    run(scenario())


def test_game_input_routes_through_application_to_real_engine() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))

        result = await send(
            harness,
            SubmitGameInput(TextInput(text="1 и 3")),
        )

        output = result.outputs[0]
        assert isinstance(output, GameActions)
        assert output.outcome_id == "correct_evidence"
        assert len(output.actions) == 2
        assert harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.current_scene == "lora_scene2"

    run(scenario())


def test_semantic_choice_revision_is_checked_through_application() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("killing_margo"))
        await send(harness, SubmitGameInput(TextInput(text="да")))
        hint = harness.sessions.sessions["session-1"]
        assert hint.engine_snapshot.current_scene == "margo_q1_hint"
        assert hint.engine_snapshot.revision == 2

        stale_result = await send(
            harness,
            SubmitGameInput(
                ChoiceInput(
                    interaction_id="hint_q1",
                    value="yes",
                    session_revision=1,
                )
            ),
        )

        stale = stale_result.outputs[0]
        assert isinstance(stale, GameActions)
        assert stale.input_status is InputStatus.STALE
        assert stale.invalid_reason is InvalidReason.REVISION_MISMATCH
        assert harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.current_scene == "margo_q1_hint"

        accepted_result = await send(
            harness,
            SubmitGameInput(
                ChoiceInput(
                    interaction_id="hint_q1",
                    value="yes",
                    session_revision=2,
                )
            ),
        )

        accepted = accepted_result.outputs[0]
        assert isinstance(accepted, GameActions)
        assert accepted.outcome_id == "q1_accept_hint"
        assert harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.current_scene == "margo_q1"

    run(scenario())


def test_margo_q9_records_scheduled_request_with_injected_clock() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("killing_margo"))
        session = harness.sessions.sessions["session-1"]
        at_q9 = replace(
            session,
            engine_snapshot=session.engine_snapshot.model_copy(
                update={"current_scene": "margo_q9", "revision": 20}
            ),
        )
        harness.sessions.sessions[session.session_id] = at_q9

        result = await send(
            harness,
            SubmitGameInput(TextInput(text="31,33")),
        )

        output = result.outputs[0]
        assert isinstance(output, GameActions)
        assert output.outcome_id == "q9_correct"
        assert [type(action) for action in output.actions[:3]] == [
            TextAction,
            TextAction,
            MediaAction,
        ]
        saved = harness.sessions.sessions["session-1"]
        assert saved.engine_snapshot.current_scene == "margo_articles"
        assert saved.engine_snapshot.revision == 21
        requests = harness.scheduled.requests["session-1"]
        assert len(requests) == 1
        assert requests[0].template_id == "reveal_articles"
        assert requests[0].due_at == NOW + timedelta(seconds=300)
        assert requests[0].idempotency_key == "reveal_articles"

    run(scenario())


def test_completion_is_persisted_and_does_not_start_another_game() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))
        await send(harness, SubmitGameInput(TextInput(text="1,2")))
        await send(harness, SubmitGameInput(TextInput(text="6")))

        completed = harness.sessions.sessions["session-1"]
        assert completed.status is ApplicationSessionStatus.COMPLETED
        assert completed.engine_snapshot.status is SessionStatus.COMPLETED
        assert completed.completed_at == NOW
        revision = completed.engine_snapshot.revision

        repeated = await send(
            harness,
            SubmitGameInput(TextInput(text="6")),
        )

        output = repeated.outputs[0]
        assert isinstance(output, GameActions)
        assert output.input_status is InputStatus.STALE
        assert output.invalid_reason is InvalidReason.INCOMPATIBLE
        assert len(harness.sessions.created_ids) == 1
        assert (
            harness.sessions.sessions["session-1"].engine_snapshot.revision
            == revision
        )

    run(scenario())


def test_restart_request_does_not_change_session() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))
        before = harness.sessions.sessions["session-1"]

        result = await send(harness, RequestRestart("session-1"))

        confirmation = result.outputs[0]
        assert isinstance(confirmation, ShowRestartConfirmation)
        assert confirmation.display_title == "Дело Лоры Дейн"
        assert harness.sessions.sessions["session-1"] == before
        assert await harness.sessions.get_selected(PLAYER) == before

    run(scenario())


def test_restart_confirm_supersedes_cancels_and_starts_latest() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        await send(harness, SubmitGameInput(TextInput(text="1,3")))

        result = await send(harness, ConfirmRestart("session-1"))

        old = harness.sessions.sessions["session-1"]
        new = harness.sessions.sessions["session-2"]
        assert old.status is ApplicationSessionStatus.SUPERSEDED
        assert old.superseded_at == NOW
        assert harness.scheduled.cancelled_session_ids == ["session-1"]
        assert new.game_version == "1.0.0"
        assert new.engine_snapshot.current_scene == "lora_scene1"
        assert await harness.sessions.get_selected(PLAYER) == new
        output = result.outputs[0]
        assert isinstance(output, GameActions)
        assert output.session_id == "session-2"
        assert isinstance(output.actions[0], TextAction)

    run(scenario())


def test_restart_cancel_keeps_old_session_selected_and_unchanged() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        before = harness.sessions.sessions["session-1"]

        result = await send(harness, CancelRestart("session-1"))

        notice = result.outputs[0]
        assert isinstance(notice, Notice)
        assert notice.code == "restart_cancelled"
        assert harness.sessions.sessions["session-1"] == before
        assert await harness.sessions.get_selected(PLAYER) == before
        assert harness.scheduled.cancelled_session_ids == []

    run(scenario())


def test_game_input_without_selected_session_returns_notice_and_menu() -> None:
    async def scenario() -> None:
        harness = make_harness()

        result = await send(
            harness,
            SubmitGameInput(TextInput(text="1,3")),
        )

        assert isinstance(result.outputs[0], Notice)
        assert result.outputs[0].code == "no_selected_session"
        assert isinstance(result.outputs[1], ShowGameMenu)
        assert harness.sessions.sessions == {}
        assert harness.sessions.saved_ids == []

    run(scenario())


def test_duplicate_external_event_mutates_engine_only_once() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"), event_id="select-1")
        action = SubmitGameInput(TextInput(text="1,3"))

        first = await send(harness, action, event_id="input-1")
        revision = harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.revision
        second = await send(harness, action, event_id="input-1")

        assert isinstance(first.outputs[0], GameActions)
        assert isinstance(second.outputs[0], DuplicateInteraction)
        assert (
            harness.sessions.sessions["session-1"].engine_snapshot.revision
            == revision
            == 2
        )
        assert harness.sessions.saved_ids == ["session-1"]

    run(scenario())


def test_in_memory_repository_rejects_stale_revision() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        stale = harness.sessions.sessions["session-1"]
        await send(harness, SubmitGameInput(TextInput(text="1,3")))

        with pytest.raises(SessionConflict):
            await harness.sessions.save(stale, expected_revision=1)

        assert harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.current_scene == "lora_scene2"

    run(scenario())


def test_missing_pinned_version_is_explicit_error_without_upgrade() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("lora_dein"))
        session = harness.sessions.sessions["session-1"]
        missing = replace(
            session,
            engine_snapshot=session.engine_snapshot.model_copy(
                update={"game_version": "9.9.9"}
            ),
        )
        harness.sessions.sessions[session.session_id] = missing

        with pytest.raises(GameVersionUnavailable) as raised:
            await send(
                harness,
                SubmitGameInput(TextInput(text="1,3")),
            )

        assert raised.value.game_version == "9.9.9"
        assert harness.sessions.saved_ids == []
        assert len(harness.sessions.created_ids) == 1

    run(scenario())


def test_session_bound_input_is_rejected_after_game_switch() -> None:
    async def scenario() -> None:
        harness = make_harness()
        await send(harness, SelectGame("killing_margo"))
        await send(harness, SelectGame("lora_dein"))

        result = await send(
            harness,
            SubmitGameInput(
                TextInput(text="нет"),
                session_id="session-1",
            ),
        )

        stale = result.outputs[0]
        assert isinstance(stale, StaleInteraction)
        assert stale.selected_session_id == "session-2"
        assert harness.sessions.saved_ids == []
        assert harness.sessions.sessions[
            "session-1"
        ].engine_snapshot.current_scene == "margo_q1_initial"

    run(scenario())
