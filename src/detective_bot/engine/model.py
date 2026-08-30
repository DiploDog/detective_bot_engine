from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


MachineId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
ChoiceValue: TypeAlias = StrictStr | StrictInt
Key = TypeVar("Key")
Value = TypeVar("Value")


class FrozenDict(dict[Key, Value]):
    """A dict-compatible mapping that rejects mutation after construction."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __ior__(self, other: object) -> FrozenDict[Key, Value]:
        del other
        self._immutable()
        return self


class EngineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetDefinition(EngineModel):
    type: Literal["image", "audio", "document", "video"]
    path: str


class GameManifest(EngineModel):
    schema_version: int
    game_id: MachineId
    version: str
    display_title: str
    description: str = ""
    language: str = "ru"
    game_file: str = "game.yaml"
    assets: dict[MachineId, AssetDefinition] = Field(default_factory=dict)

    @field_validator("assets")
    @classmethod
    def freeze_assets(
        cls, value: dict[MachineId, AssetDefinition]
    ) -> FrozenDict[MachineId, AssetDefinition]:
        return FrozenDict(value)


class VariableDefinition(EngineModel):
    type: Literal["boolean", "integer", "string"]
    default: JsonValue

    @model_validator(mode="after")
    def default_matches_declared_type(self) -> VariableDefinition:
        expected_types = {
            "boolean": bool,
            "integer": int,
            "string": str,
        }
        expected = expected_types[self.type]
        if type(self.default) is not expected:
            raise ValueError(f"default must have type {self.type}")
        return self


class ChoiceOption(EngineModel):
    label: str
    text_aliases: tuple[str, ...] = ()


class TextInputSpec(EngineModel):
    type: Literal["text"]
    normalize: tuple[
        Literal["trim", "lowercase", "collapse_whitespace", "replace_yo"], ...
    ] = ()


class NumericSelectionInputSpec(EngineModel):
    type: Literal["numeric_selection"]
    separators: tuple[Literal["comma", "whitespace", "word_and"], ...]
    unique: Literal[True] = True
    min_items: int = Field(ge=1)
    max_items: int = Field(ge=1)
    allowed_values: tuple[int, ...]


class ChoiceInputSpec(EngineModel):
    type: Literal["choice"]
    normalize: tuple[
        Literal["trim", "lowercase", "collapse_whitespace", "replace_yo"], ...
    ] = ()
    options: dict[ChoiceValue, ChoiceOption]

    @field_validator("options")
    @classmethod
    def freeze_options(
        cls, value: dict[ChoiceValue, ChoiceOption]
    ) -> FrozenDict[ChoiceValue, ChoiceOption]:
        return FrozenDict(value)


InputSpec: TypeAlias = Annotated[
    TextInputSpec | NumericSelectionInputSpec | ChoiceInputSpec,
    Field(discriminator="type"),
]


class ExactTextMatch(EngineModel):
    strategy: Literal["exact"]
    value: str


class AliasesTextMatch(EngineModel):
    strategy: Literal["aliases"]
    values: tuple[str, ...]


class ContainsTextMatch(EngineModel):
    strategy: Literal["contains"]
    values: tuple[str, ...]


TextMatch: TypeAlias = Annotated[
    ExactTextMatch | AliasesTextMatch | ContainsTextMatch,
    Field(discriminator="strategy"),
]


class TextCondition(EngineModel):
    match: TextMatch


class ChoiceCondition(EngineModel):
    choice: ChoiceValue


class SelectionSize(EngineModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class SelectionPredicate(EngineModel):
    equals: tuple[int, ...] | None = None
    subset_of: tuple[int, ...] | None = None
    size: SelectionSize | None = None
    intersection_with: tuple[int, ...] | None = None
    intersection_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def has_one_supported_predicate(self) -> SelectionPredicate:
        selected = sum(
            value is not None
            for value in (self.equals, self.subset_of, self.intersection_with)
        )
        if selected != 1:
            raise ValueError(
                "selection must define exactly one of equals, subset_of, "
                "intersection_with"
            )
        if self.subset_of is None and self.size is not None:
            raise ValueError("size is only valid with subset_of")
        if self.intersection_with is None and self.intersection_size is not None:
            raise ValueError(
                "intersection_size is only valid with intersection_with"
            )
        if self.intersection_with is not None and self.intersection_size is None:
            raise ValueError(
                "intersection_size is required with intersection_with"
            )
        return self


class SelectionCondition(EngineModel):
    selection: SelectionPredicate


WhenCondition: TypeAlias = (
    Literal["invalid", "otherwise"]
    | TextCondition
    | ChoiceCondition
    | SelectionCondition
)


class TextAction(EngineModel):
    type: Literal["text"]
    text: str


class MediaAction(EngineModel):
    type: Literal["media"]
    asset: MachineId
    caption: str | None = None


class ChoiceActionOption(EngineModel):
    value: ChoiceValue
    label: str


class ChoicesAction(EngineModel):
    type: Literal["choices"]
    interaction: MachineId
    text: str
    options: tuple[ChoiceActionOption, ...] = ()


OutputAction: TypeAlias = Annotated[
    TextAction | MediaAction | ChoicesAction,
    Field(discriminator="type"),
]


class SetVariableEffect(EngineModel):
    type: Literal["set"]
    variable: MachineId
    value: JsonValue


class IncrementVariableEffect(EngineModel):
    type: Literal["increment"]
    variable: MachineId
    by: int = 1


class ScheduleEffect(EngineModel):
    type: Literal["schedule"]
    action: MachineId
    delay_seconds: int = Field(ge=0)
    idempotency_key: str


Effect: TypeAlias = Annotated[
    SetVariableEffect | IncrementVariableEffect | ScheduleEffect,
    Field(discriminator="type"),
]


class GotoTransition(EngineModel):
    goto: MachineId


Transition: TypeAlias = Literal["stay", "complete"] | GotoTransition


class OutcomeRule(EngineModel):
    id: MachineId
    when: WhenCondition
    actions: tuple[OutputAction, ...] = ()
    effects: tuple[Effect, ...] = ()
    transition: Transition


class Interaction(EngineModel):
    id: MachineId
    input: InputSpec
    outcomes: tuple[OutcomeRule, ...]


class Fallback(EngineModel):
    actions: tuple[OutputAction, ...] = ()
    transition: Transition = "stay"


class Scene(EngineModel):
    on_enter: tuple[OutputAction, ...] = ()
    interactions: tuple[Interaction, ...] = ()
    fallback: Fallback = Field(default_factory=Fallback)


class ScheduledActionGuard(EngineModel):
    session_status: Literal["in_progress", "completed"] | None = None
    current_scene: MachineId | None = None


class ScheduledActionTemplate(EngineModel):
    guard: ScheduledActionGuard | None = None
    actions: tuple[OutputAction, ...]


class GameDefinition(EngineModel):
    schema_version: int
    entry_scene: MachineId
    variables: dict[MachineId, VariableDefinition] = Field(default_factory=dict)
    scheduled_actions: dict[MachineId, ScheduledActionTemplate] = Field(
        default_factory=dict
    )
    scenes: dict[MachineId, Scene]

    @field_validator("variables", "scheduled_actions", "scenes")
    @classmethod
    def freeze_definition_mappings(cls, value: dict) -> FrozenDict:
        return FrozenDict(value)


class GamePackage(EngineModel):
    manifest: GameManifest
    definition: GameDefinition


class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class SessionSnapshot(EngineModel):
    session_id: str
    game_id: str
    game_version: str
    current_scene: str
    status: SessionStatus
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    revision: int = Field(ge=0)

    @field_validator("variables")
    @classmethod
    def freeze_variables(
        cls, value: dict[str, JsonValue]
    ) -> FrozenDict[str, JsonValue]:
        return FrozenDict(value)


class TextInput(EngineModel):
    text: str


class ChoiceInput(EngineModel):
    interaction_id: str
    value: ChoiceValue
    session_revision: int | None = Field(default=None, ge=0)


SemanticInput: TypeAlias = TextInput | ChoiceInput


class InputStatus(StrEnum):
    HANDLED = "handled"
    INVALID = "invalid"
    FALLBACK = "fallback"
    STALE = "stale"


class InvalidReason(StrEnum):
    EMPTY = "empty"
    SYNTAX = "syntax"
    DUPLICATE = "duplicate"
    TOO_FEW = "too_few"
    TOO_MANY = "too_many"
    OUT_OF_RANGE = "out_of_range"
    INCOMPATIBLE = "incompatible"
    MISSING_REVISION = "missing_revision"
    REVISION_MISMATCH = "revision_mismatch"
    UNKNOWN_INTERACTION = "unknown_interaction"


class ScheduledActionRequest(EngineModel):
    template_id: str
    due_at: datetime
    idempotency_key: str


class EngineResult(EngineModel):
    session: SessionSnapshot
    actions: tuple[OutputAction, ...] = ()
    scheduled: tuple[ScheduledActionRequest, ...] = ()
    outcome_id: str | None = None
    interaction_id: str | None = None
    input_status: InputStatus
    invalid_reason: InvalidReason | None = None
