from __future__ import annotations

from detective_bot.engine.input import ParsedInput, ParseStatus, normalize_text
from detective_bot.engine.model import (
    AliasesTextMatch,
    ChoiceCondition,
    ChoiceInputSpec,
    ContainsTextMatch,
    ExactTextMatch,
    InputSpec,
    SelectionCondition,
    TextCondition,
    TextInputSpec,
    WhenCondition,
)


def condition_matches(
    condition: WhenCondition,
    parsed: ParsedInput,
    input_spec: InputSpec,
) -> bool:
    if condition == "invalid":
        return parsed.status is ParseStatus.INVALID
    if condition == "otherwise":
        return parsed.status is ParseStatus.VALID
    if parsed.status is not ParseStatus.VALID:
        return False

    if isinstance(condition, TextCondition):
        return _text_condition_matches(condition, parsed, input_spec)
    if isinstance(condition, ChoiceCondition):
        return (
            isinstance(input_spec, ChoiceInputSpec)
            and parsed.value == condition.choice
        )
    if isinstance(condition, SelectionCondition):
        return _selection_condition_matches(condition, parsed)
    return False


def _text_condition_matches(
    condition: TextCondition,
    parsed: ParsedInput,
    input_spec: InputSpec,
) -> bool:
    if not isinstance(input_spec, TextInputSpec) or not isinstance(parsed.value, str):
        return False

    match = condition.match
    if isinstance(match, ExactTextMatch):
        expected = normalize_text(match.value, input_spec.normalize)
        return parsed.value == expected
    if isinstance(match, AliasesTextMatch):
        aliases = {
            normalize_text(alias, input_spec.normalize) for alias in match.values
        }
        return parsed.value in aliases
    if isinstance(match, ContainsTextMatch):
        values = (
            normalize_text(value, input_spec.normalize) for value in match.values
        )
        return any(value in parsed.value for value in values)
    return False


def _selection_condition_matches(
    condition: SelectionCondition,
    parsed: ParsedInput,
) -> bool:
    if not isinstance(parsed.value, frozenset):
        return False

    selection = parsed.value
    predicate = condition.selection
    if predicate.equals is not None:
        return selection == frozenset(predicate.equals)
    if predicate.subset_of is not None:
        if not selection.issubset(predicate.subset_of):
            return False
        if predicate.size is None:
            return True
        return predicate.size.min <= len(selection) <= predicate.size.max
    if predicate.intersection_with is not None:
        return (
            len(selection.intersection(predicate.intersection_with))
            == predicate.intersection_size
        )
    return False
