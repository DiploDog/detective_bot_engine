from pathlib import Path

import pytest
from pydantic import ValidationError

from detective_bot.engine.model import GameManifest, GamePackage
from detective_bot.engine.validation import IssueSeverity, validate_package
from detective_bot.infrastructure.game_catalog import (
    PackageLoadError,
    load_game_package,
)


FIXTURES = Path(__file__).parents[2] / "fixtures"
VALID_PACKAGE = (
    FIXTURES / "games" / "synthetic_detective" / "1.10.0"
)
INVALID_PACKAGE = (
    FIXTURES / "invalid_games" / "bad_package" / "1.0.0"
)


def issue_codes(error: PackageLoadError) -> set[str]:
    return {issue.code for issue in error.issues}


def issues_for_text_match(match: dict) -> tuple:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    outcome = data["definition"]["scenes"]["aliases"]["interactions"][0][
        "outcomes"
    ][0]
    outcome["when"] = {"match": match}
    return validate_package(GamePackage.model_validate(data))


def test_valid_fixture_has_no_semantic_issues() -> None:
    loaded = load_game_package(VALID_PACKAGE)
    assert loaded.issues == ()
    assert validate_package(loaded.package) == ()


def test_validator_collects_multiple_errors_and_warnings() -> None:
    with pytest.raises(PackageLoadError) as captured:
        load_game_package(INVALID_PACKAGE)
    codes = issue_codes(captured.value)
    assert {
        "invalid_min_max",
        "otherwise_not_last",
        "unknown_variable",
        "wrong_effect_variable_type",
        "unknown_scheduled_template",
        "unknown_goto",
        "unknown_asset",
        "choices_target_unknown_interaction",
        "predicate_value_outside_allowed",
        "path_traversal",
    }.issubset(codes)
    assert any(
        issue.severity is IssueSeverity.WARNING
        for issue in captured.value.issues
    )


def test_loader_detects_duplicate_yaml_keys(tmp_path: Path) -> None:
    package = tmp_path / "duplicate_game" / "1.0.0"
    package.mkdir(parents=True)
    (package / "manifest.yaml").write_text(
        """
schema_version: 1
game_id: duplicate_game
version: 1.0.0
display_title: Duplicate
game_file: game.yaml
assets: {}
""".strip(),
        encoding="utf-8",
    )
    (package / "game.yaml").write_text(
        """
schema_version: 1
entry_scene: start
entry_scene: repeated
variables: {}
scheduled_actions: {}
scenes: {}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(PackageLoadError) as captured:
        load_game_package(package)
    assert "duplicate_yaml_key" in issue_codes(captured.value)


def test_loader_reports_missing_asset(tmp_path: Path) -> None:
    package = tmp_path / "missing_media" / "1.0.0"
    package.mkdir(parents=True)
    (package / "manifest.yaml").write_text(
        """
schema_version: 1
game_id: missing_media
version: 1.0.0
display_title: Missing media
game_file: game.yaml
assets:
  report:
    type: document
    path: assets/report.pdf
""".strip(),
        encoding="utf-8",
    )
    (package / "game.yaml").write_text(
        """
schema_version: 1
entry_scene: start
variables: {}
scheduled_actions: {}
scenes:
  start:
    on_enter:
      - type: media
        asset: report
    interactions:
      - id: finish
        input:
          type: text
        outcomes:
          - id: done
            when: otherwise
            transition: complete
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(PackageLoadError) as captured:
        load_game_package(package)
    assert "missing_asset" in issue_codes(captured.value)


def test_loader_reports_invalid_transition_shape(tmp_path: Path) -> None:
    package = tmp_path / "bad_transition" / "1.0.0"
    package.mkdir(parents=True)
    (package / "manifest.yaml").write_text(
        """
schema_version: 1
game_id: bad_transition
version: 1.0.0
display_title: Bad transition
game_file: game.yaml
assets: {}
""".strip(),
        encoding="utf-8",
    )
    (package / "game.yaml").write_text(
        """
schema_version: 1
entry_scene: start
variables: {}
scheduled_actions: {}
scenes:
  start:
    interactions:
      - id: answer
        input:
          type: text
        outcomes:
          - id: broken
            when: otherwise
            transition:
              jump: nowhere
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(PackageLoadError) as captured:
        load_game_package(package)
    assert "invalid_transition" in issue_codes(captured.value)


def test_validator_reports_incompatible_predicate_input() -> None:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    outcomes = data["definition"]["scenes"]["aliases"]["interactions"][0][
        "outcomes"
    ]
    outcomes[0]["when"] = {"selection": {"equals": [1]}}
    incompatible = GamePackage.model_validate(data)
    codes = {issue.code for issue in validate_package(incompatible)}
    assert "incompatible_predicate_input" in codes


@pytest.mark.parametrize(
    "match",
    [
        {"strategy": "exact", "value": ""},
        {"strategy": "aliases", "values": [""]},
        {"strategy": "contains", "values": [""]},
    ],
)
def test_validator_rejects_empty_normalized_match_values(
    match: dict,
) -> None:
    assert "empty_match_value" in {
        issue.code for issue in issues_for_text_match(match)
    }


def test_validator_rejects_duplicate_normalized_aliases_without_shadow_warning(
) -> None:
    issues = issues_for_text_match(
        {
            "strategy": "aliases",
            "values": ["ЛЕО", "лео"],
        }
    )
    assert "duplicate_match_value" in {issue.code for issue in issues}
    assert "shadowed_outcome" not in {issue.code for issue in issues}


def test_validator_rejects_duplicate_normalized_contains_values() -> None:
    issues = issues_for_text_match(
        {
            "strategy": "contains",
            "values": ["МАРК", "марк"],
        }
    )
    assert "duplicate_match_value" in {issue.code for issue in issues}


def test_validator_preserves_short_nonempty_contains_warning() -> None:
    issues = issues_for_text_match(
        {
            "strategy": "contains",
            "values": ["не"],
        }
    )
    assert "very_short_contains" in {issue.code for issue in issues}
    assert "empty_match_value" not in {issue.code for issue in issues}


def test_validator_rejects_intersection_larger_than_input_maximum() -> None:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    partial = data["definition"]["scenes"]["pair"]["interactions"][0][
        "outcomes"
    ][2]
    partial["when"] = {
        "selection": {
            "intersection_with": [11, 17, 20],
            "intersection_size": 3,
        }
    }
    issues = validate_package(GamePackage.model_validate(data))
    assert any(
        issue.code == "impossible_intersection_size"
        and "max_items" in issue.message
        for issue in issues
    )


def test_validator_reports_duplicate_ids() -> None:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    interaction = data["definition"]["scenes"]["code"]["interactions"][0]
    outcomes = list(interaction["outcomes"])
    outcomes.append(outcomes[0])
    interaction["outcomes"] = outcomes
    duplicate = GamePackage.model_validate(data)
    assert "duplicate_outcome_id" in {
        issue.code for issue in validate_package(duplicate)
    }


def test_validator_warns_about_unreachable_scene() -> None:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    data["definition"]["scenes"]["isolated"] = data["definition"]["scenes"][
        "finish"
    ]
    modified = GamePackage.model_validate(data)
    issues = validate_package(modified)
    assert any(
        issue.code == "unreachable_scene"
        and issue.path.endswith(".isolated")
        and issue.severity is IssueSeverity.WARNING
        for issue in issues
    )


def test_validator_reports_unsupported_schema_versions() -> None:
    package = load_game_package(VALID_PACKAGE).package
    modified = package.model_copy(
        update={
            "manifest": package.manifest.model_copy(
                update={"schema_version": 2}
            )
        }
    )
    assert "unsupported_schema_version" in {
        issue.code for issue in validate_package(modified)
    }


def test_validator_reports_choice_conflicts_and_incomplete_coverage() -> None:
    package = load_game_package(VALID_PACKAGE).package
    data = package.model_dump(mode="python")
    hint = data["definition"]["scenes"]["hint"]
    interaction = hint["interactions"][0]
    interaction["input"]["options"]["yes"]["text_aliases"] = ["same"]
    interaction["input"]["options"]["no"]["text_aliases"] = ["same"]
    interaction["outcomes"] = interaction["outcomes"][:1]
    hint["on_enter"][0]["options"] = [
        {"value": "yes", "label": "Yes"},
        {"value": "yes", "label": "Again"},
    ]
    modified = GamePackage.model_validate(data)
    issues = validate_package(modified)
    codes = {issue.code for issue in issues}
    assert "choice_alias_conflict" in codes
    assert "unhandled_choice_value" in codes
    assert "duplicate_choice_action_value" in codes


def test_manifest_rejects_enabled_inside_immutable_version() -> None:
    with pytest.raises(ValidationError):
        GameManifest.model_validate(
            {
                "schema_version": 1,
                "game_id": "example",
                "version": "1.0.0",
                "display_title": "Example",
                "enabled": True,
            }
        )
