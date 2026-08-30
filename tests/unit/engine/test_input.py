import pytest
from pydantic import ValidationError

from detective_bot.engine.input import (
    ParseStatus,
    normalize_text,
    parse_numeric_selection,
)
from detective_bot.engine.model import (
    InvalidReason,
    NumericSelectionInputSpec,
)


def numeric_spec(
    *,
    separators: tuple[str, ...] = ("comma", "whitespace", "word_and"),
    min_items: int = 2,
    max_items: int = 3,
    allowed_values: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
) -> NumericSelectionInputSpec:
    return NumericSelectionInputSpec(
        type="numeric_selection",
        separators=separators,
        unique=True,
        min_items=min_items,
        max_items=max_items,
        allowed_values=allowed_values,
    )


def test_normalization_pipeline() -> None:
    assert normalize_text("  ЁЖ   И  ЁЛКА  ", ("trim",)) == "ЁЖ   И  ЁЛКА"
    assert normalize_text(" ЛеО ", ("trim", "lowercase")) == "лео"
    assert (
        normalize_text(
            "  ЁЖ   И  ЁЛКА  ",
            ("trim", "lowercase", "collapse_whitespace", "replace_yo"),
        )
        == "еж и елка"
    )


def test_normalization_has_no_implicit_replace_yo() -> None:
    assert normalize_text("ёж", ("trim", "lowercase")) == "ёж"
    assert normalize_text("ёж", ("trim", "lowercase")) != "еж"


def test_numeric_parser_supports_declared_separators() -> None:
    spec = numeric_spec()
    for text in ("1,3", "1 3", "1 и 3", "1, 2 и 3"):
        parsed = parse_numeric_selection(spec, text)
        assert parsed.status is ParseStatus.VALID
        expected = frozenset({1, 2, 3}) if "2" in text else frozenset({1, 3})
        assert parsed.value == expected


def test_numeric_parser_rejects_unsupported_separator() -> None:
    parsed = parse_numeric_selection(
        numeric_spec(separators=("comma",)),
        "1;3",
    )
    assert parsed.status is ParseStatus.INVALID
    assert parsed.invalid_reason is InvalidReason.SYNTAX


def test_numeric_parser_rejects_undeclared_comma_separator() -> None:
    parsed = parse_numeric_selection(
        numeric_spec(separators=("whitespace",)),
        "1,3",
    )
    assert parsed.status is ParseStatus.INVALID
    assert parsed.invalid_reason is InvalidReason.SYNTAX


def test_numeric_parser_rejects_duplicate_instead_of_deduplicating() -> None:
    parsed = parse_numeric_selection(numeric_spec(), "1,1,3")
    assert parsed.status is ParseStatus.INVALID
    assert parsed.invalid_reason is InvalidReason.DUPLICATE


def test_numeric_parser_cardinality_and_range_errors() -> None:
    spec = numeric_spec()
    assert parse_numeric_selection(spec, "").invalid_reason is InvalidReason.EMPTY
    assert parse_numeric_selection(spec, "1").invalid_reason is InvalidReason.TOO_FEW
    assert (
        parse_numeric_selection(spec, "1,2,3,4").invalid_reason
        is InvalidReason.TOO_MANY
    )
    assert (
        parse_numeric_selection(spec, "1,9").invalid_reason
        is InvalidReason.OUT_OF_RANGE
    )


def test_numeric_parser_does_not_extract_embedded_digits() -> None:
    parsed = parse_numeric_selection(numeric_spec(), "1abc3")
    assert parsed.status is ParseStatus.INVALID
    assert parsed.invalid_reason is InvalidReason.SYNTAX


def test_numeric_parser_returns_no_match_for_non_numeric_text() -> None:
    parsed = parse_numeric_selection(numeric_spec(), "готов назвать убийцу")
    assert parsed.status is ParseStatus.NO_MATCH


@pytest.mark.parametrize(
    ("min_items", "max_items"),
    [(0, 1), (1, 0)],
)
def test_numeric_selection_rejects_zero_cardinality(
    min_items: int,
    max_items: int,
) -> None:
    with pytest.raises(ValidationError):
        numeric_spec(min_items=min_items, max_items=max_items)
