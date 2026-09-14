from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from detective_bot.engine.model import (
    InputStatus,
    InvalidReason,
    OutputAction,
    SemanticInput,
    SessionSnapshot,
    SessionStatus,
)


class Platform(StrEnum):
    TELEGRAM = "telegram"
    VK = "vk"


@dataclass(frozen=True, slots=True)
class PlayerContext:
    platform: Platform
    external_user_id: str
    external_chat_id: str


class ApplicationSessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ApplicationSession:
    player_context: PlayerContext
    engine_snapshot: SessionSnapshot
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.engine_snapshot.status is SessionStatus.COMPLETED
            and self.completed_at is None
        ):
            raise ValueError("completed engine snapshot requires completed_at")
        if (
            self.engine_snapshot.status is SessionStatus.IN_PROGRESS
            and self.completed_at is not None
        ):
            raise ValueError("in-progress engine snapshot cannot have completed_at")

    @property
    def session_id(self) -> str:
        return self.engine_snapshot.session_id

    @property
    def game_id(self) -> str:
        return self.engine_snapshot.game_id

    @property
    def game_version(self) -> str:
        return self.engine_snapshot.game_version

    @property
    def status(self) -> ApplicationSessionStatus:
        if self.superseded_at is not None:
            return ApplicationSessionStatus.SUPERSEDED
        if self.engine_snapshot.status is SessionStatus.COMPLETED:
            return ApplicationSessionStatus.COMPLETED
        return ApplicationSessionStatus.IN_PROGRESS


@dataclass(frozen=True, slots=True)
class OpenMenu:
    pass


@dataclass(frozen=True, slots=True)
class LeaveToMenu:
    pass


@dataclass(frozen=True, slots=True)
class SelectGame:
    game_id: str


@dataclass(frozen=True, slots=True)
class RequestRestart:
    session_id: str


@dataclass(frozen=True, slots=True)
class ConfirmRestart:
    session_id: str


@dataclass(frozen=True, slots=True)
class CancelRestart:
    session_id: str


@dataclass(frozen=True, slots=True)
class SubmitGameInput:
    value: SemanticInput
    session_id: str | None = None


ApplicationInteraction: TypeAlias = (
    OpenMenu
    | LeaveToMenu
    | SelectGame
    | RequestRestart
    | ConfirmRestart
    | CancelRestart
    | SubmitGameInput
)


@dataclass(frozen=True, slots=True)
class IncomingInteraction:
    player_context: PlayerContext
    action: ApplicationInteraction
    external_event_id: str | None = None


class MenuEntryState(StrEnum):
    NEW = "new"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class MenuGame:
    game_id: str
    game_version: str
    display_title: str
    state: MenuEntryState
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class ShowGameMenu:
    games: tuple[MenuGame, ...]


@dataclass(frozen=True, slots=True)
class ShowRestartConfirmation:
    session_id: str
    game_id: str
    display_title: str


@dataclass(frozen=True, slots=True)
class GameActions:
    session_id: str
    actions: tuple[OutputAction, ...]
    outcome_id: str | None = None
    interaction_id: str | None = None
    input_status: InputStatus = InputStatus.HANDLED
    invalid_reason: InvalidReason | None = None


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    text: str


@dataclass(frozen=True, slots=True)
class DuplicateInteraction:
    external_event_id: str


@dataclass(frozen=True, slots=True)
class StaleInteraction:
    expected_session_id: str
    selected_session_id: str | None


ApplicationOutput: TypeAlias = (
    ShowGameMenu
    | ShowRestartConfirmation
    | GameActions
    | Notice
    | DuplicateInteraction
    | StaleInteraction
)


@dataclass(frozen=True, slots=True)
class ApplicationResult:
    outputs: tuple[ApplicationOutput, ...] = ()


class InteractionInputKind(StrEnum):
    TEXT = "text"
    CHOICE = "choice"


@dataclass(frozen=True, slots=True)
class SessionInteractionRecord:
    session_id: str
    external_event_id: str | None
    scene_before: str | None
    scene_after: str | None
    interaction_id: str | None
    outcome_id: str | None
    input_kind: InteractionInputKind
    input_status: InputStatus
    invalid_reason: InvalidReason | None
    created_at: datetime


class ScheduledActionStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DEAD = "dead"


class OutboundDeliveryStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class StoredScheduledAction:
    action_id: int
    session_id: str
    player_context: PlayerContext
    game_id: str
    game_version: str
    template_id: str
    origin_revision: int
    due_at: datetime
    idempotency_key: str
    status: ScheduledActionStatus
    attempts: int
    claimed_at: datetime | None
    lease_until: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    next_attempt_at: datetime | None
    last_error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    player_context: PlayerContext
    session_id: str | None
    source_event_id: str | None
    sequence_no: int
    action_payload: dict
    status: OutboundDeliveryStatus
    due_at: datetime
    created_at: datetime
    attempts: int = 0
    claimed_at: datetime | None = None
    lease_until: datetime | None = None
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    delivery_id: int | None = None
