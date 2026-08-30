from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from detective_bot.engine.model import (
    ChoiceInput,
    ChoicesAction,
    GamePackage,
    InputStatus,
    InvalidReason,
    MediaAction,
    SessionSnapshot,
    SessionStatus,
    TextAction,
    TextInput,
)
from detective_bot.engine.runner import EngineExecutionError, GameEngine
from detective_bot.infrastructure.game_catalog import load_game_package


PACKAGE_ROOT = (
    Path(__file__).parents[2]
    / "fixtures"
    / "games"
    / "synthetic_detective"
    / "1.10.0"
)
PACKAGE = load_game_package(PACKAGE_ROOT).package
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def session(
    scene: str = "",
    *,
    revision: int = 0,
    status: SessionStatus = SessionStatus.IN_PROGRESS,
    variables: dict | None = None,
) -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-1",
        game_id="synthetic_detective",
        game_version="1.10.0",
        current_scene=scene,
        status=status,
        variables=variables or {"safe_opened": False, "wrong_attempts": 0},
        revision=revision,
    )


def action_texts(result_actions: tuple) -> list[str]:
    return [
        action.text
        for action in result_actions
        if isinstance(action, TextAction)
    ]


def test_start_enters_entry_scene_and_initializes_variables() -> None:
    result = GameEngine().start(PACKAGE, session(variables={}), NOW)
    assert result.session.current_scene == "aliases"
    assert result.session.revision == 1
    assert result.session.variables == {
        "safe_opened": False,
        "wrong_attempts": 0,
    }
    assert action_texts(result.actions) == ["Name the visitor."]


def test_start_rejects_incompatible_or_already_started_session() -> None:
    with pytest.raises(EngineExecutionError):
        GameEngine().start(PACKAGE, session("aliases"), NOW)
    wrong_game = session().model_copy(update={"game_id": "other"})
    with pytest.raises(EngineExecutionError):
        GameEngine().start(PACKAGE, wrong_game, NOW)


def test_output_only_stay_does_not_repeat_on_enter_or_advance_revision() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("aliases", revision=4),
        TextInput(text="unknown"),
        NOW,
    )
    assert result.outcome_id == "wrong_name"
    assert result.session.current_scene == "aliases"
    assert result.session.revision == 4
    assert action_texts(result.actions) == ["Try again."]


def test_goto_appends_destination_on_enter_after_outcome_actions() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("aliases", revision=1),
        TextInput(text="  ЛЕО  "),
        NOW,
    )
    assert result.outcome_id == "leo"
    assert result.session.current_scene == "code"
    assert action_texts(result.actions) == ["Correct.", "Enter the safe code."]


def test_effects_and_action_order_are_deterministic() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("code", revision=2),
        TextInput(text=" 1503 "),
        NOW,
    )
    assert result.session.variables["safe_opened"] is True
    assert result.session.current_scene == "pair"
    assert isinstance(result.actions[0], TextAction)
    assert isinstance(result.actions[1], MediaAction)
    assert isinstance(result.actions[2], TextAction)
    assert result.actions[2].text == "Choose evidence 11 and 17."


def test_partial_numeric_pair_stays_in_scene() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("pair", revision=3),
        TextInput(text="11,20"),
        NOW,
    )
    assert result.outcome_id == "pair_partial"
    assert result.session.current_scene == "pair"
    assert action_texts(result.actions) == ["One clue is correct."]


def test_first_matching_outcome_wins() -> None:
    data = PACKAGE.model_dump(mode="python")
    interaction = data["definition"]["scenes"]["finish"]["interactions"][0]
    outcomes = list(interaction["outcomes"])
    outcomes.insert(
        0,
        {
            "id": "first_mark_rule",
            "when": {
                "match": {
                    "strategy": "contains",
                    "values": ["mark"],
                }
            },
            "actions": [{"type": "text", "text": "First rule."}],
            "effects": [],
            "transition": "stay",
        },
    )
    interaction["outcomes"] = outcomes
    package = GamePackage.model_validate(data)
    result = GameEngine().handle(
        package,
        session("finish", revision=7),
        TextInput(text="Mark"),
        NOW,
    )
    assert result.outcome_id == "first_mark_rule"
    assert result.session.status is SessionStatus.IN_PROGRESS


@pytest.mark.parametrize("answer", ["1,2", "1,6", "2,6", "1,2,6"])
def test_threshold_subset_accepts_all_lora_like_successes(answer: str) -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("threshold", revision=4),
        TextInput(text=answer),
        NOW,
    )
    assert result.outcome_id == "suspects_correct"
    assert result.session.current_scene == "hint"
    assert isinstance(result.actions[-1], ChoicesAction)


def test_threshold_subset_rejects_foreign_value_and_reenters_scene() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("threshold", revision=4),
        TextInput(text="1,3"),
        NOW,
    )
    assert result.outcome_id == "suspects_wrong"
    assert result.session.variables["wrong_attempts"] == 1
    assert action_texts(result.actions) == [
        "That set contains a wrong suspect.",
        "Choose two or three suspects.",
    ]


def test_invalid_input_is_distinct_and_duplicates_are_not_deduplicated() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("pair", revision=3),
        TextInput(text="11,11"),
        NOW,
    )
    assert result.input_status is InputStatus.INVALID
    assert result.invalid_reason is InvalidReason.DUPLICATE
    assert result.outcome_id == "pair_invalid"
    assert result.session.revision == 3


def test_semantic_choice_schedules_with_injected_clock() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("hint", revision=5),
        ChoiceInput(
            interaction_id="hint_decision",
            value="yes",
            session_revision=5,
        ),
        NOW,
    )
    assert result.outcome_id == "hint_yes"
    assert result.session.current_scene == "articles"
    assert len(result.scheduled) == 1
    assert result.scheduled[0].template_id == "reveal_articles"
    assert result.scheduled[0].due_at == NOW + timedelta(seconds=300)
    assert result.scheduled[0].idempotency_key == "reveal_articles"


def test_typed_text_can_select_choice_alias() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("hint", revision=5),
        TextInput(text=" ДА "),
        NOW,
    )
    assert result.outcome_id == "hint_yes"
    assert result.session.current_scene == "articles"


@pytest.mark.parametrize(
    ("choice", "reason"),
    [
        (
            ChoiceInput(
                interaction_id="hint_decision",
                value="yes",
                session_revision=None,
            ),
            InvalidReason.MISSING_REVISION,
        ),
        (
            ChoiceInput(
                interaction_id="hint_decision",
                value="yes",
                session_revision=4,
            ),
            InvalidReason.REVISION_MISMATCH,
        ),
        (
            ChoiceInput(
                interaction_id="missing",
                value="yes",
                session_revision=5,
            ),
            InvalidReason.UNKNOWN_INTERACTION,
        ),
        (
            ChoiceInput(
                interaction_id="readiness",
                value="yes",
                session_revision=5,
            ),
            InvalidReason.INCOMPATIBLE,
        ),
    ],
)
def test_stale_or_incompatible_choice_does_not_mutate_session(
    choice: ChoiceInput,
    reason: InvalidReason,
) -> None:
    original = session(
        "hint" if choice.interaction_id != "readiness" else "articles",
        revision=5,
    )
    result = GameEngine().handle(PACKAGE, original, choice, NOW)
    assert result.input_status is InputStatus.STALE
    assert result.invalid_reason is reason
    assert result.session == original
    assert result.actions == ()


def test_articles_route_readiness_before_numeric_selection() -> None:
    ready = GameEngine().handle(
        PACKAGE,
        session("articles", revision=6),
        TextInput(text="  ГОТОВ   НАЗВАТЬ УБИЙЦУ "),
        NOW,
    )
    assert ready.outcome_id == "ready"
    assert ready.session.current_scene == "finish"

    article = GameEngine().handle(
        PACKAGE,
        session("articles", revision=6),
        TextInput(text="2"),
        NOW,
    )
    assert article.outcome_id == "article_2"
    assert article.session.current_scene == "articles"


def test_numeric_semantic_choice_routes_to_article_interaction() -> None:
    result = GameEngine().handle(
        PACKAGE,
        session("articles", revision=6),
        ChoiceInput(
            interaction_id="read_article",
            value=3,
            session_revision=6,
        ),
        NOW,
    )
    assert result.outcome_id == "article_3"
    assert result.session.current_scene == "articles"
    assert result.session.revision == 6
    assert action_texts(result.actions) == ["Article three."]


def test_reusable_article_choices_remain_current_after_output_only_stay() -> None:
    original = session("articles", revision=6)
    first = GameEngine().handle(
        PACKAGE,
        original,
        ChoiceInput(
            interaction_id="read_article",
            value=1,
            session_revision=6,
        ),
        NOW,
    )
    second = GameEngine().handle(
        PACKAGE,
        first.session,
        ChoiceInput(
            interaction_id="read_article",
            value=2,
            session_revision=6,
        ),
        NOW,
    )
    assert first.session.revision == second.session.revision == 6
    assert second.outcome_id == "article_2"


def test_scene_fallback_only_sends_output_without_revision_change() -> None:
    original = session("articles", revision=6)
    result = GameEngine().handle(
        PACKAGE,
        original,
        TextInput(text="not ready"),
        NOW,
    )
    assert result.input_status is InputStatus.FALLBACK
    assert result.session == original
    assert action_texts(result.actions) == [
        "Choose article 1-3 or state readiness."
    ]


def test_complete_transition_and_completed_session_rejection() -> None:
    completed = GameEngine().handle(
        PACKAGE,
        session("finish", revision=7),
        TextInput(text="It was Mark."),
        NOW,
    )
    assert completed.outcome_id == "complete_game"
    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.session.revision == 8

    repeated = GameEngine().handle(
        PACKAGE,
        completed.session,
        TextInput(text="Mark"),
        NOW,
    )
    assert repeated.input_status is InputStatus.STALE
    assert repeated.session.revision == 8


@pytest.mark.parametrize(
    "variables",
    [
        {"safe_opened": False},
        {
            "safe_opened": False,
            "wrong_attempts": 0,
            "unknown": True,
        },
        {"safe_opened": "no", "wrong_attempts": 0},
    ],
)
def test_malformed_persisted_session_variables_are_rejected(
    variables: dict,
) -> None:
    with pytest.raises(EngineExecutionError):
        GameEngine().handle(
            PACKAGE,
            session("aliases", variables=variables),
            TextInput(text="лео"),
            NOW,
        )


def test_session_variables_are_deeply_immutable() -> None:
    snapshot = session("aliases")
    with pytest.raises(TypeError):
        snapshot.variables["wrong_attempts"] = 2
