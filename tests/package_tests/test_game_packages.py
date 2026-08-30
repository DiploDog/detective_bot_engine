from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from detective_bot.engine.model import (
    ChoiceInput,
    InputStatus,
    MediaAction,
    SessionSnapshot,
    SessionStatus,
    TextAction,
    TextInput,
)
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import load_game_package


PROJECT_ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PackageCase:
    package_root: Path
    source: Path
    name: str
    initial: dict[str, Any]
    steps: tuple[dict[str, Any], ...]


def discover_package_cases() -> tuple[PackageCase, ...]:
    discovered: list[PackageCase] = []
    for source in sorted((PROJECT_ROOT / "games").glob("*/*/tests/*.yaml")):
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        package_root = source.parent.parent
        suite_name = document["name"]
        if "steps" in document:
            discovered.append(
                PackageCase(
                    package_root=package_root,
                    source=source,
                    name=suite_name,
                    initial=document.get("initial", {}),
                    steps=tuple(document["steps"]),
                )
            )
        for index, case in enumerate(document.get("cases", [])):
            discovered.append(
                PackageCase(
                    package_root=package_root,
                    source=source,
                    name=case.get("name", f"{suite_name}_{index + 1}"),
                    initial=case.get("initial", {}),
                    steps=(
                        {
                            "input": case["input"],
                            "expect": case["expect"],
                        },
                    ),
                )
            )
    return tuple(discovered)


PACKAGE_CASES = discover_package_cases()


@pytest.mark.parametrize(
    "case",
    PACKAGE_CASES,
    ids=lambda case: f"{case.source.name}::{case.name}",
)
def test_game_package_case(case: PackageCase) -> None:
    loaded = load_game_package(case.package_root)
    package = loaded.package
    defaults = {
        name: definition.default
        for name, definition in package.definition.variables.items()
    }
    defaults.update(case.initial.get("variables", {}))
    session = SessionSnapshot(
        session_id=f"package-test:{case.name}",
        game_id=package.manifest.game_id,
        game_version=package.manifest.version,
        current_scene=case.initial.get("scene", ""),
        status=case.initial.get("status", SessionStatus.IN_PROGRESS),
        variables=defaults if case.initial.get("scene") else {},
        revision=case.initial.get("revision", 0),
    )
    engine = GameEngine()

    for step in case.steps:
        if step.get("start"):
            result = engine.start(package, session, NOW)
        elif "set_scene" in step:
            session = session.model_copy(
                update={"current_scene": step["set_scene"]}
            )
            continue
        else:
            semantic_input = _semantic_input(step["input"], session.revision)
            result = engine.handle(package, session, semantic_input, NOW)
        _assert_result(result, step["expect"])
        session = result.session


def _semantic_input(data: dict[str, Any], revision: int) -> TextInput | ChoiceInput:
    if "text" in data:
        return TextInput(text=data["text"])
    choice = data["choice"]
    return ChoiceInput(
        interaction_id=choice["interaction"],
        value=choice["value"],
        session_revision=choice.get("session_revision", revision),
    )


def _assert_result(result: Any, expected: dict[str, Any]) -> None:
    if "scene" in expected:
        assert result.session.current_scene == expected["scene"]
    if "status" in expected:
        assert result.session.status == expected["status"]
    if "outcome" in expected:
        assert result.outcome_id == expected["outcome"]
    if "input_status" in expected:
        assert result.input_status == InputStatus(expected["input_status"])
    if "invalid_reason" in expected:
        actual_reason = (
            result.invalid_reason.value
            if result.invalid_reason is not None
            else None
        )
        assert actual_reason == expected["invalid_reason"]
    for name, value in expected.get("variables", {}).items():
        assert result.session.variables[name] == value
    if "actions" in expected:
        assert len(result.actions) == len(expected["actions"])
        for actual, action_expected in zip(
            result.actions,
            expected["actions"],
            strict=True,
        ):
            assert actual.type == action_expected["type"]
            if isinstance(actual, TextAction):
                if "exact" in action_expected:
                    assert actual.text == action_expected["exact"]
                if "contains" in action_expected:
                    assert action_expected["contains"] in actual.text
            if isinstance(actual, MediaAction) and "asset" in action_expected:
                assert actual.asset == action_expected["asset"]
