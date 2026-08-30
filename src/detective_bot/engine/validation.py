from __future__ import annotations

from collections import defaultdict, deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from detective_bot.engine.input import normalize_text
from detective_bot.engine.model import (
    AliasesTextMatch,
    ChoiceCondition,
    ChoiceInputSpec,
    ChoicesAction,
    ContainsTextMatch,
    ExactTextMatch,
    GamePackage,
    GotoTransition,
    IncrementVariableEffect,
    MediaAction,
    NumericSelectionInputSpec,
    OutputAction,
    SelectionCondition,
    SetVariableEffect,
    ScheduleEffect,
    TextCondition,
    TextInputSpec,
)


class IssueSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: IssueSeverity
    code: str
    path: str
    message: str


def validate_package(package: GamePackage) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    manifest = package.manifest
    game = package.definition

    if manifest.schema_version != 1:
        _error(
            issues,
            "unsupported_schema_version",
            "manifest.schema_version",
            f"unsupported manifest schema version: {manifest.schema_version}",
        )
    if game.schema_version != 1:
        _error(
            issues,
            "unsupported_schema_version",
            "definition.schema_version",
            f"unsupported game schema version: {game.schema_version}",
        )
    if game.entry_scene not in game.scenes:
        _error(
            issues,
            "missing_entry_scene",
            "definition.entry_scene",
            f"entry scene does not exist: {game.entry_scene}",
        )

    used_variables: set[str] = set()
    used_assets: set[str] = set()
    edges: dict[str, set[str]] = defaultdict(set)
    complete_scenes: set[str] = set()

    for scene_id, scene in game.scenes.items():
        scene_path = f"definition.scenes.{scene_id}"
        interaction_ids = [interaction.id for interaction in scene.interactions]
        _report_duplicates(
            issues,
            interaction_ids,
            "duplicate_interaction_id",
            f"{scene_path}.interactions",
        )
        interactions = {
            interaction.id: interaction for interaction in scene.interactions
        }

        _validate_actions(
            issues,
            scene.on_enter,
            f"{scene_path}.on_enter",
            manifest.assets,
            interactions,
            used_assets,
        )
        _validate_actions(
            issues,
            scene.fallback.actions,
            f"{scene_path}.fallback.actions",
            manifest.assets,
            interactions,
            used_assets,
        )
        _validate_transition(
            issues,
            scene_id,
            scene.fallback.transition,
            f"{scene_path}.fallback.transition",
            game.scenes,
            edges,
            complete_scenes,
        )

        for interaction_index, interaction in enumerate(scene.interactions):
            interaction_path = (
                f"{scene_path}.interactions[{interaction_index}]"
            )
            _validate_input_spec(issues, interaction.input, interaction_path)
            outcome_ids = [outcome.id for outcome in interaction.outcomes]
            _report_duplicates(
                issues,
                outcome_ids,
                "duplicate_outcome_id",
                f"{interaction_path}.outcomes",
            )
            otherwise_positions = [
                index
                for index, outcome in enumerate(interaction.outcomes)
                if outcome.when == "otherwise"
            ]
            if len(otherwise_positions) > 1:
                _error(
                    issues,
                    "multiple_otherwise",
                    f"{interaction_path}.outcomes",
                    "an interaction may contain only one otherwise outcome",
                )
            if otherwise_positions and otherwise_positions[-1] != len(
                interaction.outcomes
            ) - 1:
                _error(
                    issues,
                    "otherwise_not_last",
                    f"{interaction_path}.outcomes[{otherwise_positions[-1]}]",
                    "otherwise must be the last outcome",
                )
            if (
                otherwise_positions
                and interaction_index != len(scene.interactions) - 1
            ):
                _error(
                    issues,
                    "otherwise_shadows_interactions",
                    f"{interaction_path}.outcomes[{otherwise_positions[-1]}]",
                    "otherwise in a non-final interaction shadows later interactions",
                )
            _validate_outcome_coverage_and_shadowing(
                issues,
                interaction.input,
                interaction.outcomes,
                f"{interaction_path}.outcomes",
            )

            for outcome_index, outcome in enumerate(interaction.outcomes):
                outcome_path = (
                    f"{interaction_path}.outcomes[{outcome_index}]"
                )
                _validate_condition(
                    issues,
                    interaction.input,
                    outcome.when,
                    f"{outcome_path}.when",
                )
                _validate_actions(
                    issues,
                    outcome.actions,
                    f"{outcome_path}.actions",
                    manifest.assets,
                    interactions,
                    used_assets,
                )
                for effect_index, effect in enumerate(outcome.effects):
                    effect_path = f"{outcome_path}.effects[{effect_index}]"
                    if isinstance(effect, SetVariableEffect):
                        definition = game.variables.get(effect.variable)
                        if definition is None:
                            _error(
                                issues,
                                "unknown_variable",
                                f"{effect_path}.variable",
                                f"unknown variable: {effect.variable}",
                            )
                        else:
                            used_variables.add(effect.variable)
                            if not _value_matches_type(
                                effect.value, definition.type
                            ):
                                _error(
                                    issues,
                                    "wrong_effect_variable_type",
                                    f"{effect_path}.value",
                                    f"value does not match {definition.type}",
                                )
                    elif isinstance(effect, IncrementVariableEffect):
                        definition = game.variables.get(effect.variable)
                        if definition is None:
                            _error(
                                issues,
                                "unknown_variable",
                                f"{effect_path}.variable",
                                f"unknown variable: {effect.variable}",
                            )
                        else:
                            used_variables.add(effect.variable)
                            if definition.type != "integer":
                                _error(
                                    issues,
                                    "wrong_effect_variable_type",
                                    f"{effect_path}.variable",
                                    "increment requires an integer variable",
                                )
                    elif isinstance(effect, ScheduleEffect):
                        if effect.action not in game.scheduled_actions:
                            _error(
                                issues,
                                "unknown_scheduled_template",
                                f"{effect_path}.action",
                                f"unknown scheduled template: {effect.action}",
                            )
                _validate_transition(
                    issues,
                    scene_id,
                    outcome.transition,
                    f"{outcome_path}.transition",
                    game.scenes,
                    edges,
                    complete_scenes,
                )

    for template_id, template in game.scheduled_actions.items():
        template_path = f"definition.scheduled_actions.{template_id}"
        if template.guard is None:
            _warning(
                issues,
                "scheduled_action_without_guard",
                f"{template_path}.guard",
                "scheduled action has no session guard",
            )
        target_interactions: dict = {}
        if template.guard is not None and template.guard.current_scene is not None:
            guarded_scene = game.scenes.get(template.guard.current_scene)
            if guarded_scene is None:
                _error(
                    issues,
                    "unknown_guard_scene",
                    f"{template_path}.guard.current_scene",
                    f"unknown guard scene: {template.guard.current_scene}",
                )
            else:
                target_interactions = {
                    interaction.id: interaction
                    for interaction in guarded_scene.interactions
                }
        _validate_actions(
            issues,
            template.actions,
            f"{template_path}.actions",
            manifest.assets,
            target_interactions,
            used_assets,
        )

    for variable in game.variables:
        if variable not in used_variables:
            _warning(
                issues,
                "unused_variable",
                f"definition.variables.{variable}",
                f"variable is never changed by an effect: {variable}",
            )
    for asset in manifest.assets:
        if asset not in used_assets:
            _warning(
                issues,
                "unused_asset",
                f"manifest.assets.{asset}",
                f"asset is never referenced: {asset}",
            )

    reachable = _reachable_from(game.entry_scene, edges)
    for scene_id in game.scenes:
        if scene_id not in reachable:
            _warning(
                issues,
                "unreachable_scene",
                f"definition.scenes.{scene_id}",
                f"scene is unreachable from entry scene: {scene_id}",
            )

    can_complete = _scenes_reaching_completion(game.scenes, edges, complete_scenes)
    for scene_id in game.scenes:
        if scene_id not in can_complete:
            _warning(
                issues,
                "no_completion_path",
                f"definition.scenes.{scene_id}",
                f"no apparent path from scene to completion: {scene_id}",
            )

    return tuple(issues)


def has_errors(issues: tuple[ValidationIssue, ...]) -> bool:
    return any(issue.severity is IssueSeverity.ERROR for issue in issues)


def _validate_input_spec(
    issues: list[ValidationIssue],
    input_spec: TextInputSpec | NumericSelectionInputSpec | ChoiceInputSpec,
    path: str,
) -> None:
    if isinstance(input_spec, NumericSelectionInputSpec):
        if input_spec.min_items > input_spec.max_items:
            _error(
                issues,
                "invalid_min_max",
                f"{path}.input",
                "min_items must not exceed max_items",
            )
        if len(input_spec.allowed_values) != len(set(input_spec.allowed_values)):
            _error(
                issues,
                "duplicate_allowed_value",
                f"{path}.input.allowed_values",
                "allowed_values must not contain duplicates",
            )
        if input_spec.min_items > len(set(input_spec.allowed_values)):
            _error(
                issues,
                "impossible_input_cardinality",
                f"{path}.input.min_items",
                "min_items exceeds the number of unique allowed_values",
            )
    if isinstance(input_spec, ChoiceInputSpec) and not input_spec.options:
        _error(
            issues,
            "empty_choice_options",
            f"{path}.input.options",
            "choice input must define at least one option",
        )
    if isinstance(input_spec, ChoiceInputSpec):
        aliases: dict[str, str | int] = {}
        labels: dict[str, str | int] = {}
        for value, option in input_spec.options.items():
            normalized_label = option.label.strip().lower()
            if (
                normalized_label in labels
                and labels[normalized_label] != value
            ):
                _warning(
                    issues,
                    "choice_label_conflict",
                    f"{path}.input.options",
                    f"choice label is shared by {labels[normalized_label]!r} "
                    f"and {value!r}",
                )
            labels[normalized_label] = value
            for alias in option.text_aliases:
                normalized_alias = normalize_text(alias, input_spec.normalize)
                if (
                    normalized_alias in aliases
                    and aliases[normalized_alias] != value
                ):
                    _warning(
                        issues,
                        "choice_alias_conflict",
                        f"{path}.input.options",
                        f"typed alias is shared by {aliases[normalized_alias]!r} "
                        f"and {value!r}",
                    )
                aliases[normalized_alias] = value


def _validate_condition(
    issues: list[ValidationIssue],
    input_spec: TextInputSpec | NumericSelectionInputSpec | ChoiceInputSpec,
    condition: object,
    path: str,
) -> None:
    if condition in ("invalid", "otherwise"):
        return
    if isinstance(condition, TextCondition):
        if not isinstance(input_spec, TextInputSpec):
            _error(
                issues,
                "incompatible_predicate_input",
                path,
                "text predicate requires text input",
            )
            return
        match = condition.match
        if isinstance(match, ExactTextMatch):
            normalized = normalize_text(match.value, input_spec.normalize)
            if not normalized:
                _error(
                    issues,
                    "empty_match_value",
                    path,
                    "exact match value is empty after normalization",
                )
        elif isinstance(match, (AliasesTextMatch, ContainsTextMatch)):
            normalized_values = [
                normalize_text(value, input_spec.normalize)
                for value in match.values
            ]
            if any(not value for value in normalized_values):
                _error(
                    issues,
                    "empty_match_value",
                    path,
                    f"{match.strategy} contains an empty value after normalization",
                )
            if len(normalized_values) != len(set(normalized_values)):
                _error(
                    issues,
                    "duplicate_match_value",
                    path,
                    f"{match.strategy} contains duplicate values after normalization",
                )
            if isinstance(match, ContainsTextMatch):
                for value in normalized_values:
                    if value and len(value) < 3:
                        _warning(
                            issues,
                            "very_short_contains",
                            path,
                            f"contains value is very short: {value!r}",
                        )
        return
    if isinstance(condition, ChoiceCondition):
        if not isinstance(input_spec, ChoiceInputSpec):
            _error(
                issues,
                "incompatible_predicate_input",
                path,
                "choice predicate requires choice input",
            )
        elif condition.choice not in input_spec.options:
            _error(
                issues,
                "unknown_choice_value",
                path,
                f"unknown choice value: {condition.choice}",
            )
        return
    if isinstance(condition, SelectionCondition):
        if not isinstance(input_spec, NumericSelectionInputSpec):
            _error(
                issues,
                "incompatible_predicate_input",
                path,
                "selection predicate requires numeric_selection input",
            )
            return
        predicate = condition.selection
        values = next(
            (
                candidate
                for candidate in (
                    predicate.equals,
                    predicate.subset_of,
                    predicate.intersection_with,
                )
                if candidate is not None
            ),
            (),
        )
        if len(values) != len(set(values)):
            _error(
                issues,
                "duplicate_predicate_value",
                path,
                "selection predicate values must be unique",
            )
        outside = set(values).difference(input_spec.allowed_values)
        if outside:
            _error(
                issues,
                "predicate_value_outside_allowed",
                path,
                f"predicate values are outside allowed_values: {sorted(outside)}",
            )
        if predicate.size is not None:
            if predicate.size.min > predicate.size.max:
                _error(
                    issues,
                    "invalid_min_max",
                    path,
                    "selection size min must not exceed max",
                )
            if (
                predicate.size.min < input_spec.min_items
                or predicate.size.max > input_spec.max_items
            ):
                _error(
                    issues,
                    "predicate_size_outside_input",
                    path,
                    "selection size falls outside input cardinality",
                )
            if (
                predicate.subset_of is not None
                and predicate.size.min > len(set(predicate.subset_of))
            ):
                _error(
                    issues,
                    "impossible_predicate_size",
                    path,
                    "selection size min exceeds subset_of cardinality",
                )
        if predicate.equals is not None and not (
            input_spec.min_items
            <= len(set(predicate.equals))
            <= input_spec.max_items
        ):
            _error(
                issues,
                "predicate_size_outside_input",
                path,
                "equals cardinality falls outside input cardinality",
            )
        if (
            predicate.intersection_with is not None
            and predicate.intersection_size is not None
            and predicate.intersection_size
            > len(set(predicate.intersection_with))
        ):
            _error(
                issues,
                "impossible_intersection_size",
                path,
                "intersection_size exceeds intersection_with cardinality",
            )
        if (
            predicate.intersection_with is not None
            and predicate.intersection_size is not None
            and predicate.intersection_size > input_spec.max_items
        ):
            _error(
                issues,
                "impossible_intersection_size",
                path,
                "intersection_size exceeds input max_items",
            )


def _validate_outcome_coverage_and_shadowing(
    issues: list[ValidationIssue],
    input_spec: TextInputSpec | NumericSelectionInputSpec | ChoiceInputSpec,
    outcomes: tuple,
    path: str,
) -> None:
    has_otherwise = any(outcome.when == "otherwise" for outcome in outcomes)
    if isinstance(input_spec, ChoiceInputSpec) and not has_otherwise:
        handled_values = {
            outcome.when.choice
            for outcome in outcomes
            if isinstance(outcome.when, ChoiceCondition)
        }
        missing = set(input_spec.options).difference(handled_values)
        if missing:
            _error(
                issues,
                "unhandled_choice_value",
                path,
                f"choice values have no outcome: {sorted(missing, key=str)}",
            )

    seen: dict[object, int] = {}
    for index, outcome in enumerate(outcomes):
        condition = outcome.when
        keys: tuple[object, ...] = ()
        if isinstance(input_spec, TextInputSpec) and isinstance(
            condition, TextCondition
        ):
            match = condition.match
            if isinstance(match, ExactTextMatch):
                values = (match.value,)
            elif isinstance(match, (AliasesTextMatch, ContainsTextMatch)):
                values = match.values
            else:
                values = ()
            keys = tuple(
                (
                    match.strategy,
                    normalize_text(value, input_spec.normalize),
                )
                for value in values
            )
        elif isinstance(condition, ChoiceCondition):
            keys = (("choice", condition.choice),)
        elif (
            isinstance(condition, SelectionCondition)
            and condition.selection.equals is not None
        ):
            keys = (("equals", frozenset(condition.selection.equals)),)

        for key in set(keys):
            if key in seen:
                _warning(
                    issues,
                    "shadowed_outcome",
                    f"{path}[{index}]",
                    f"condition duplicates earlier outcome at index {seen[key]}",
                )
            else:
                seen[key] = index


def _validate_actions(
    issues: list[ValidationIssue],
    actions: tuple[OutputAction, ...],
    path: str,
    assets: dict,
    interactions: dict,
    used_assets: set[str],
) -> None:
    for index, action in enumerate(actions):
        action_path = f"{path}[{index}]"
        if isinstance(action, MediaAction):
            if action.asset not in assets:
                _error(
                    issues,
                    "unknown_asset",
                    f"{action_path}.asset",
                    f"unknown asset: {action.asset}",
                )
            else:
                used_assets.add(action.asset)
        elif isinstance(action, ChoicesAction):
            option_values = [option.value for option in action.options]
            if len(option_values) != len(set(option_values)):
                _error(
                    issues,
                    "duplicate_choice_action_value",
                    f"{action_path}.options",
                    "choices action values must be unique",
                )
            interaction = interactions.get(action.interaction)
            if interaction is None:
                _error(
                    issues,
                    "choices_target_unknown_interaction",
                    f"{action_path}.interaction",
                    f"unknown interaction: {action.interaction}",
                )
                continue
            if isinstance(interaction.input, ChoiceInputSpec):
                if action.options:
                    allowed = set(interaction.input.options)
                    provided = {option.value for option in action.options}
                    if not provided.issubset(allowed):
                        _error(
                            issues,
                            "choice_action_value_not_allowed",
                            f"{action_path}.options",
                            "choice action contains a value not accepted by input",
                        )
            elif isinstance(interaction.input, NumericSelectionInputSpec):
                if not action.options:
                    _error(
                        issues,
                        "numeric_choices_require_options",
                        f"{action_path}.options",
                        "numeric choices action requires explicit options",
                    )
                allowed = set(interaction.input.allowed_values)
                provided = {option.value for option in action.options}
                if not provided.issubset(allowed):
                    _error(
                        issues,
                        "choice_action_value_not_allowed",
                        f"{action_path}.options",
                        "choice action contains a value not accepted by input",
                    )
            else:
                _error(
                    issues,
                    "choices_target_incompatible_input",
                    f"{action_path}.interaction",
                    "choices action requires choice or numeric_selection input",
                )


def _validate_transition(
    issues: list[ValidationIssue],
    source_scene: str,
    transition: object,
    path: str,
    scenes: dict,
    edges: dict[str, set[str]],
    complete_scenes: set[str],
) -> None:
    if transition == "stay":
        edges[source_scene].add(source_scene)
    elif transition == "complete":
        complete_scenes.add(source_scene)
    elif isinstance(transition, GotoTransition):
        if transition.goto not in scenes:
            _error(
                issues,
                "unknown_goto",
                path,
                f"unknown destination scene: {transition.goto}",
            )
        else:
            edges[source_scene].add(transition.goto)
    else:
        _error(
            issues,
            "invalid_transition",
            path,
            f"unsupported transition: {transition!r}",
        )


def _report_duplicates(
    issues: list[ValidationIssue],
    values: list[str],
    code: str,
    path: str,
) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            _error(issues, code, path, f"duplicate id: {value}")
        seen.add(value)


def _reachable_from(entry_scene: str, edges: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    queue = deque([entry_scene])
    while queue:
        scene = queue.popleft()
        if scene in reachable:
            continue
        reachable.add(scene)
        queue.extend(edges.get(scene, ()))
    return reachable


def _scenes_reaching_completion(
    scenes: dict,
    edges: dict[str, set[str]],
    complete_scenes: set[str],
) -> set[str]:
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, destinations in edges.items():
        for destination in destinations:
            reverse[destination].add(source)
    can_complete = set(complete_scenes)
    queue = deque(complete_scenes)
    while queue:
        scene = queue.popleft()
        for source in reverse.get(scene, ()):
            if source not in can_complete:
                can_complete.add(source)
                queue.append(source)
    return can_complete.intersection(scenes)


def _value_matches_type(value: object, declared_type: str) -> bool:
    return (
        (declared_type == "boolean" and type(value) is bool)
        or (declared_type == "integer" and type(value) is int)
        or (declared_type == "string" and type(value) is str)
    )


def _error(
    issues: list[ValidationIssue],
    code: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        ValidationIssue(
            severity=IssueSeverity.ERROR,
            code=code,
            path=path,
            message=message,
        )
    )


def _warning(
    issues: list[ValidationIssue],
    code: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        ValidationIssue(
            severity=IssueSeverity.WARNING,
            code=code,
            path=path,
            message=message,
        )
    )
