from detective_bot.engine.input import ParsedInput, ParseStatus
from detective_bot.engine.matching import condition_matches
from detective_bot.engine.model import (
    AliasesTextMatch,
    ContainsTextMatch,
    ExactTextMatch,
    SelectionCondition,
    SelectionPredicate,
    SelectionSize,
    TextCondition,
    TextInputSpec,
    NumericSelectionInputSpec,
)


TEXT_SPEC = TextInputSpec(
    type="text",
    normalize=("trim", "lowercase", "replace_yo"),
)
NUMERIC_SPEC = NumericSelectionInputSpec(
    type="numeric_selection",
    separators=("comma",),
    unique=True,
    min_items=1,
    max_items=3,
    allowed_values=(1, 2, 3, 6, 11, 17),
)


def test_exact_and_aliases_use_declared_normalization() -> None:
    parsed = ParsedInput(ParseStatus.VALID, "лео")
    exact = TextCondition(
        match=ExactTextMatch(strategy="exact", value=" ЛЕО ")
    )
    aliases = TextCondition(
        match=AliasesTextMatch(
            strategy="aliases",
            values=("ЛЕО", "Лео Миллер"),
        )
    )
    assert condition_matches(exact, parsed, TEXT_SPEC)
    assert condition_matches(aliases, parsed, TEXT_SPEC)


def test_contains_is_explicit_substring_matching() -> None:
    parsed = ParsedInput(ParseStatus.VALID, "это был марк вчера")
    condition = TextCondition(
        match=ContainsTextMatch(strategy="contains", values=("МАРК",))
    )
    assert condition_matches(condition, parsed, TEXT_SPEC)


def test_selection_equals_is_order_independent() -> None:
    condition = SelectionCondition(
        selection=SelectionPredicate(equals=(11, 17))
    )
    parsed = ParsedInput(ParseStatus.VALID, frozenset({17, 11}))
    assert condition_matches(condition, parsed, NUMERIC_SPEC)


def test_selection_subset_applies_size_threshold() -> None:
    condition = SelectionCondition(
        selection=SelectionPredicate(
            subset_of=(1, 2, 6),
            size=SelectionSize(min=2, max=3),
        )
    )
    assert condition_matches(
        condition,
        ParsedInput(ParseStatus.VALID, frozenset({1, 6})),
        NUMERIC_SPEC,
    )
    assert not condition_matches(
        condition,
        ParsedInput(ParseStatus.VALID, frozenset({1, 3})),
        NUMERIC_SPEC,
    )


def test_selection_intersection_count() -> None:
    condition = SelectionCondition(
        selection=SelectionPredicate(
            intersection_with=(11, 17),
            intersection_size=1,
        )
    )
    assert condition_matches(
        condition,
        ParsedInput(ParseStatus.VALID, frozenset({11, 2})),
        NUMERIC_SPEC,
    )
