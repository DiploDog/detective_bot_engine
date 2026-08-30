from __future__ import annotations

from datetime import datetime, timedelta

from detective_bot.engine.input import ParsedInput, ParseStatus, parse_text_input
from detective_bot.engine.matching import condition_matches
from detective_bot.engine.model import (
    ChoiceInput,
    ChoiceInputSpec,
    EngineResult,
    Fallback,
    FrozenDict,
    GamePackage,
    GotoTransition,
    IncrementVariableEffect,
    InputSpec,
    InputStatus,
    Interaction,
    InvalidReason,
    NumericSelectionInputSpec,
    OutcomeRule,
    OutputAction,
    ScheduleEffect,
    ScheduledActionRequest,
    SemanticInput,
    SessionSnapshot,
    SessionStatus,
    SetVariableEffect,
    TextInput,
    TextInputSpec,
    Transition,
)


class EngineExecutionError(ValueError):
    """Raised when a validated definition and session are inconsistent."""


class GameEngine:
    def start(
        self,
        package: GamePackage,
        session: SessionSnapshot,
        now: datetime,
    ) -> EngineResult:
        del now  # Start is deterministic and currently has no time-based effect.
        self._ensure_compatible(package, session)
        if session.status is not SessionStatus.IN_PROGRESS:
            raise EngineExecutionError("only an in-progress session can be started")
        if session.current_scene:
            raise EngineExecutionError("session has already entered a scene")

        entry_scene = package.definition.scenes.get(package.definition.entry_scene)
        if entry_scene is None:
            raise EngineExecutionError("entry scene does not exist")

        variables = {
            name: definition.default
            for name, definition in package.definition.variables.items()
        }
        started = session.model_copy(
            update={
                "current_scene": package.definition.entry_scene,
                "variables": FrozenDict(variables),
                "revision": session.revision + 1,
            }
        )
        return EngineResult(
            session=started,
            actions=entry_scene.on_enter,
            input_status=InputStatus.HANDLED,
        )

    def handle(
        self,
        package: GamePackage,
        session: SessionSnapshot,
        semantic_input: SemanticInput,
        now: datetime,
    ) -> EngineResult:
        self._ensure_compatible(package, session)
        self._ensure_session_variables(package, session)
        if session.status is SessionStatus.COMPLETED:
            return self._stale(session, InvalidReason.INCOMPATIBLE)

        scene = package.definition.scenes.get(session.current_scene)
        if scene is None:
            raise EngineExecutionError(
                f"current scene does not exist: {session.current_scene}"
            )

        if isinstance(semantic_input, ChoiceInput):
            return self._handle_choice(
                package, session, semantic_input, now
            )

        for interaction in scene.interactions:
            parsed = parse_text_input(interaction.input, semantic_input.text)
            if parsed.status is ParseStatus.NO_MATCH:
                continue
            if parsed.status is ParseStatus.INVALID:
                outcome = self._find_invalid_outcome(interaction, parsed)
                if outcome is not None:
                    return self._execute_outcome(
                        package=package,
                        session=session,
                        interaction=interaction,
                        outcome=outcome,
                        parsed=parsed,
                        now=now,
                        input_status=InputStatus.INVALID,
                    )
                return self._execute_fallback(
                    package,
                    session,
                    scene.fallback,
                    parsed.invalid_reason,
                    interaction.id,
                )

            outcome = self._find_matching_outcome(interaction, parsed)
            if outcome is not None:
                return self._execute_outcome(
                    package=package,
                    session=session,
                    interaction=interaction,
                    outcome=outcome,
                    parsed=parsed,
                    now=now,
                    input_status=InputStatus.HANDLED,
                )

        return self._execute_fallback(package, session, scene.fallback)

    def _handle_choice(
        self,
        package: GamePackage,
        session: SessionSnapshot,
        semantic_input: ChoiceInput,
        now: datetime,
    ) -> EngineResult:
        if semantic_input.session_revision is None:
            return self._stale(session, InvalidReason.MISSING_REVISION)
        if (
            semantic_input.session_revision != session.revision
        ):
            return self._stale(session, InvalidReason.REVISION_MISMATCH)

        scene = package.definition.scenes[session.current_scene]
        interaction = next(
            (
                candidate
                for candidate in scene.interactions
                if candidate.id == semantic_input.interaction_id
            ),
            None,
        )
        if interaction is None:
            return self._stale(session, InvalidReason.UNKNOWN_INTERACTION)

        parsed = self._parse_choice(interaction.input, semantic_input.value)
        if parsed is None:
            return self._stale(session, InvalidReason.INCOMPATIBLE)
        if parsed.status is ParseStatus.INVALID:
            outcome = self._find_invalid_outcome(interaction, parsed)
            if outcome is None:
                return self._stale(
                    session,
                    parsed.invalid_reason or InvalidReason.INCOMPATIBLE,
                )
            return self._execute_outcome(
                package=package,
                session=session,
                interaction=interaction,
                outcome=outcome,
                parsed=parsed,
                now=now,
                input_status=InputStatus.INVALID,
            )

        outcome = self._find_matching_outcome(interaction, parsed)
        if outcome is None:
            return self._execute_fallback(
                package,
                session,
                scene.fallback,
                interaction_id=interaction.id,
            )
        return self._execute_outcome(
            package=package,
            session=session,
            interaction=interaction,
            outcome=outcome,
            parsed=parsed,
            now=now,
            input_status=InputStatus.HANDLED,
        )

    @staticmethod
    def _parse_choice(
        input_spec: InputSpec,
        value: str | int,
    ) -> ParsedInput | None:
        if isinstance(input_spec, ChoiceInputSpec):
            if value not in input_spec.options:
                return None
            return ParsedInput(status=ParseStatus.VALID, value=value)
        if isinstance(input_spec, NumericSelectionInputSpec):
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            parsed = parse_text_input(input_spec, str(value))
            return parsed
        if isinstance(input_spec, TextInputSpec):
            return None
        return None

    @staticmethod
    def _find_invalid_outcome(
        interaction: Interaction,
        parsed: ParsedInput,
    ) -> OutcomeRule | None:
        return next(
            (
                outcome
                for outcome in interaction.outcomes
                if condition_matches(outcome.when, parsed, interaction.input)
            ),
            None,
        )

    @staticmethod
    def _find_matching_outcome(
        interaction: Interaction,
        parsed: ParsedInput,
    ) -> OutcomeRule | None:
        return next(
            (
                outcome
                for outcome in interaction.outcomes
                if condition_matches(outcome.when, parsed, interaction.input)
            ),
            None,
        )

    def _execute_outcome(
        self,
        *,
        package: GamePackage,
        session: SessionSnapshot,
        interaction: Interaction,
        outcome: OutcomeRule,
        parsed: ParsedInput,
        now: datetime,
        input_status: InputStatus,
    ) -> EngineResult:
        variables = dict(session.variables)
        scheduled: list[ScheduledActionRequest] = []

        for effect in outcome.effects:
            if isinstance(effect, SetVariableEffect):
                self._apply_set(package, variables, effect)
            elif isinstance(effect, IncrementVariableEffect):
                self._apply_increment(package, variables, effect)
            elif isinstance(effect, ScheduleEffect):
                if effect.action not in package.definition.scheduled_actions:
                    raise EngineExecutionError(
                        f"unknown scheduled action: {effect.action}"
                    )
                scheduled.append(
                    ScheduledActionRequest(
                        template_id=effect.action,
                        due_at=now + timedelta(seconds=effect.delay_seconds),
                        idempotency_key=effect.idempotency_key,
                    )
                )
            else:
                raise EngineExecutionError(
                    f"unsupported effect: {type(effect).__name__}"
                )

        transitioned, enter_actions = self._transition(
            package,
            session.model_copy(update={"variables": FrozenDict(variables)}),
            outcome.transition,
        )
        mutates_state = bool(outcome.effects) or outcome.transition != "stay"
        mutated = (
            transitioned.model_copy(
                update={"revision": session.revision + 1}
            )
            if mutates_state
            else transitioned
        )
        return EngineResult(
            session=mutated,
            actions=outcome.actions + enter_actions,
            scheduled=tuple(scheduled),
            outcome_id=outcome.id,
            interaction_id=interaction.id,
            input_status=input_status,
            invalid_reason=(
                parsed.invalid_reason
                if input_status is InputStatus.INVALID
                else None
            ),
        )

    def _execute_fallback(
        self,
        package: GamePackage,
        session: SessionSnapshot,
        fallback: Fallback,
        invalid_reason: InvalidReason | None = None,
        interaction_id: str | None = None,
    ) -> EngineResult:
        transitioned, enter_actions = self._transition(
            package, session, fallback.transition
        )
        changed = fallback.transition != "stay"
        if changed:
            transitioned = transitioned.model_copy(
                update={"revision": session.revision + 1}
            )
        return EngineResult(
            session=transitioned,
            actions=fallback.actions + enter_actions,
            input_status=(
                InputStatus.INVALID
                if invalid_reason is not None
                else InputStatus.FALLBACK
            ),
            invalid_reason=invalid_reason,
            interaction_id=interaction_id,
        )

    @staticmethod
    def _transition(
        package: GamePackage,
        session: SessionSnapshot,
        transition: Transition,
    ) -> tuple[SessionSnapshot, tuple[OutputAction, ...]]:
        if transition == "stay":
            return session, ()
        if transition == "complete":
            return session.model_copy(update={"status": SessionStatus.COMPLETED}), ()
        if isinstance(transition, GotoTransition):
            destination = package.definition.scenes.get(transition.goto)
            if destination is None:
                raise EngineExecutionError(
                    f"unknown destination scene: {transition.goto}"
                )
            return (
                session.model_copy(update={"current_scene": transition.goto}),
                destination.on_enter,
            )
        raise EngineExecutionError(f"unsupported transition: {transition!r}")

    @staticmethod
    def _apply_set(
        package: GamePackage,
        variables: dict,
        effect: SetVariableEffect,
    ) -> None:
        definition = package.definition.variables.get(effect.variable)
        if definition is None:
            raise EngineExecutionError(f"unknown variable: {effect.variable}")
        if not _value_matches_type(effect.value, definition.type):
            raise EngineExecutionError(
                f"value for {effect.variable} must be {definition.type}"
            )
        variables[effect.variable] = effect.value

    @staticmethod
    def _apply_increment(
        package: GamePackage,
        variables: dict,
        effect: IncrementVariableEffect,
    ) -> None:
        definition = package.definition.variables.get(effect.variable)
        if definition is None:
            raise EngineExecutionError(f"unknown variable: {effect.variable}")
        if definition.type != "integer":
            raise EngineExecutionError(
                f"cannot increment non-integer variable: {effect.variable}"
            )
        current = variables[effect.variable]
        if type(current) is not int:
            raise EngineExecutionError(
                f"session variable {effect.variable} is not an integer"
            )
        variables[effect.variable] = current + effect.by

    @staticmethod
    def _ensure_compatible(
        package: GamePackage,
        session: SessionSnapshot,
    ) -> None:
        if session.game_id != package.manifest.game_id:
            raise EngineExecutionError("session game_id does not match package")
        if session.game_version != package.manifest.version:
            raise EngineExecutionError(
                "session game_version does not match package"
            )

    @staticmethod
    def _ensure_session_variables(
        package: GamePackage,
        session: SessionSnapshot,
    ) -> None:
        definitions = package.definition.variables
        if set(session.variables) != set(definitions):
            raise EngineExecutionError(
                "session variables do not match game definition"
            )
        for name, definition in definitions.items():
            if not _value_matches_type(
                session.variables[name],
                definition.type,
            ):
                raise EngineExecutionError(
                    f"session variable {name} must be {definition.type}"
                )

    @staticmethod
    def _stale(
        session: SessionSnapshot,
        reason: InvalidReason,
    ) -> EngineResult:
        return EngineResult(
            session=session,
            input_status=InputStatus.STALE,
            invalid_reason=reason,
        )


def _value_matches_type(value: object, declared_type: str) -> bool:
    if declared_type == "boolean":
        return type(value) is bool
    if declared_type == "integer":
        return type(value) is int
    if declared_type == "string":
        return type(value) is str
    return False
