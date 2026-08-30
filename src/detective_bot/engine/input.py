from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from detective_bot.engine.model import (
    ChoiceInputSpec,
    InputSpec,
    InvalidReason,
    NumericSelectionInputSpec,
    TextInputSpec,
)


class ParseStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    NO_MATCH = "no_match"


ParsedValue = str | int | frozenset[int]


@dataclass(frozen=True, slots=True)
class ParsedInput:
    status: ParseStatus
    value: ParsedValue | None = None
    invalid_reason: InvalidReason | None = None


def normalize_text(text: str, pipeline: tuple[str, ...]) -> str:
    normalized = text
    for step in pipeline:
        if step == "trim":
            normalized = normalized.strip()
        elif step == "lowercase":
            normalized = normalized.lower()
        elif step == "collapse_whitespace":
            normalized = " ".join(normalized.split())
        elif step == "replace_yo":
            normalized = normalized.replace("ё", "е").replace("Ё", "Е")
        else:  # The typed model prevents this for loaded definitions.
            raise ValueError(f"unsupported normalization step: {step}")
    return normalized


def parse_text_input(spec: InputSpec, text: str) -> ParsedInput:
    if isinstance(spec, TextInputSpec):
        return ParsedInput(
            status=ParseStatus.VALID,
            value=normalize_text(text, spec.normalize),
        )
    if isinstance(spec, NumericSelectionInputSpec):
        return parse_numeric_selection(spec, text)
    if isinstance(spec, ChoiceInputSpec):
        normalized = normalize_text(text, spec.normalize)
        for value, option in spec.options.items():
            normalized_aliases = (
                normalize_text(alias, spec.normalize)
                for alias in option.text_aliases
            )
            if normalized in normalized_aliases:
                return ParsedInput(status=ParseStatus.VALID, value=value)
        return ParsedInput(status=ParseStatus.NO_MATCH)
    raise TypeError(f"unsupported input spec: {type(spec).__name__}")


def parse_numeric_selection(
    spec: NumericSelectionInputSpec, text: str
) -> ParsedInput:
    delimiter = "\x00"
    raw = text.strip()
    if not raw:
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.EMPTY,
        )
    if re.search(r"[0-9]", raw) is None:
        return ParsedInput(status=ParseStatus.NO_MATCH)

    tokenized = raw
    if "word_and" in spec.separators:
        tokenized = re.sub(
            r"(?<=[0-9])\s+[иИ]\s+(?=[0-9])",
            delimiter,
            tokenized,
        )
    if "comma" in spec.separators:
        tokenized = re.sub(r"\s*,\s*", delimiter, tokenized)
    if "whitespace" in spec.separators:
        tokenized = re.sub(
            r"(?<=[0-9])\s+(?=[0-9])",
            delimiter,
            tokenized,
        )

    tokens = tokenized.split(delimiter)
    if not tokens or any(re.fullmatch(r"[0-9]+", token) is None for token in tokens):
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.SYNTAX,
        )

    values = [int(token) for token in tokens]
    if spec.unique and len(values) != len(set(values)):
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.DUPLICATE,
        )
    if len(values) < spec.min_items:
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.TOO_FEW,
        )
    if len(values) > spec.max_items:
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.TOO_MANY,
        )
    allowed = set(spec.allowed_values)
    if any(value not in allowed for value in values):
        return ParsedInput(
            status=ParseStatus.INVALID,
            invalid_reason=InvalidReason.OUT_OF_RANGE,
        )
    return ParsedInput(
        status=ParseStatus.VALID,
        value=frozenset(values),
    )
