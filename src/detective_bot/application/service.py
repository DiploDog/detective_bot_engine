from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from detective_bot.application.models import (
    ApplicationResult,
    ApplicationSession,
    CancelRestart,
    ConfirmRestart,
    DuplicateInteraction,
    GameActions,
    IncomingInteraction,
    InteractionInputKind,
    LeaveToMenu,
    MenuEntryState,
    MenuGame,
    Notice,
    OpenMenu,
    PlayerContext,
    RequestRestart,
    SelectGame,
    SessionInteractionRecord,
    ShowGameMenu,
    ShowRestartConfirmation,
    StaleInteraction,
    SubmitGameInput,
)
from detective_bot.application.outbound import build_outbound_deliveries
from detective_bot.application.ports import (
    ApplicationUnitOfWork,
    Clock,
    GameCatalogPort,
    SessionIdFactory,
    UnitOfWorkFactory,
)
from detective_bot.engine.model import (
    GamePackage,
    OutputAction,
    SessionSnapshot,
    SessionStatus,
    TextInput,
)
from detective_bot.engine.runner import GameEngine


class ApplicationError(RuntimeError):
    pass


class SessionNotFound(ApplicationError):
    pass


class GameVersionUnavailable(ApplicationError):
    def __init__(self, game_id: str, game_version: str | None = None) -> None:
        self.game_id = game_id
        self.game_version = game_version
        reference = (
            game_id if game_version is None else f"{game_id}/{game_version}"
        )
        super().__init__(f"game package is unavailable: {reference}")


class InvalidApplicationInteraction(ApplicationError):
    pass


class ApplicationService:
    def __init__(
        self,
        *,
        catalog: GameCatalogPort,
        uow_factory: UnitOfWorkFactory,
        engine: GameEngine,
        clock: Clock,
        session_id_factory: SessionIdFactory,
    ) -> None:
        self._catalog = catalog
        self._uow_factory = uow_factory
        self._engine = engine
        self._clock = clock
        self._session_id_factory = session_id_factory

    async def handle(self, interaction: IncomingInteraction) -> ApplicationResult:
        now = self._clock()
        event_id = interaction.external_event_id
        player = interaction.player_context
        async with self._uow_factory() as uow:
            if event_id is not None and not await uow.processed_events.try_register(
                player,
                event_id,
                processed_at=now,
            ):
                return ApplicationResult((DuplicateInteraction(event_id),))
            result = await self._dispatch(
                uow,
                player,
                interaction.action,
                now,
                event_id,
            )
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=event_id,
            )

    async def open_menu(self, player: PlayerContext) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._open_menu(uow, player, now)
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def select_game(
        self,
        player: PlayerContext,
        game_id: str,
    ) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._select_game(uow, player, game_id, now)
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def submit_game_input(
        self,
        player: PlayerContext,
        game_input: SubmitGameInput,
    ) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._submit_game_input(
                uow,
                player,
                game_input,
                now,
                None,
            )
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def request_restart(
        self,
        player: PlayerContext,
        session_id: str,
    ) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._request_restart(uow, player, session_id)
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def confirm_restart(
        self,
        player: PlayerContext,
        session_id: str,
    ) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._confirm_restart(uow, player, session_id, now)
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def cancel_restart(
        self,
        player: PlayerContext,
        session_id: str,
    ) -> ApplicationResult:
        now = self._clock()
        async with self._uow_factory() as uow:
            result = await self._cancel_restart(uow, player, session_id)
            return await self._commit_with_outbound(
                uow,
                player,
                result,
                now=now,
                event_id=None,
            )

    async def _dispatch(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        action: object,
        now: datetime,
        external_event_id: str | None,
    ) -> ApplicationResult:
        if isinstance(action, OpenMenu):
            return await self._open_menu(uow, player, now)
        if isinstance(action, LeaveToMenu):
            return await self._leave_to_menu(uow, player, now)
        if isinstance(action, SelectGame):
            return await self._select_game(uow, player, action.game_id, now)
        if isinstance(action, SubmitGameInput):
            return await self._submit_game_input(
                uow,
                player,
                action,
                now,
                external_event_id,
            )
        if isinstance(action, RequestRestart):
            return await self._request_restart(uow, player, action.session_id)
        if isinstance(action, ConfirmRestart):
            return await self._confirm_restart(
                uow,
                player,
                action.session_id,
                now,
            )
        if isinstance(action, CancelRestart):
            return await self._cancel_restart(uow, player, action.session_id)
        raise InvalidApplicationInteraction(
            f"unsupported interaction: {type(action).__name__}"
        )

    async def _open_menu(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        now: datetime,
    ) -> ApplicationResult:
        await uow.sessions.set_selected(player, None, updated_at=now)
        return ApplicationResult((await self._build_menu(uow, player),))

    async def _leave_to_menu(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        now: datetime,
    ) -> ApplicationResult:
        await uow.sessions.set_selected(player, None, updated_at=now)
        return ApplicationResult(
            (
                Notice("left_to_menu", "Прогресс сохранён."),
                await self._build_menu(uow, player),
            )
        )

    async def _build_menu(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
    ) -> ShowGameMenu:
        resumable = {
            session.game_id: session
            for session in await uow.sessions.list_resumable(player)
        }
        games: list[MenuGame] = []
        for game_id in self._catalog.list_games():
            session = resumable.get(game_id)
            package = (
                self._get_pinned(session)
                if session is not None
                else self._get_latest(game_id)
            )
            manifest = package.manifest
            games.append(
                MenuGame(
                    game_id=game_id,
                    game_version=manifest.version,
                    display_title=manifest.display_title,
                    state=(
                        MenuEntryState.CONTINUE
                        if session is not None
                        else MenuEntryState.NEW
                    ),
                    session_id=(
                        session.session_id if session is not None else None
                    ),
                )
            )
        return ShowGameMenu(tuple(games))

    async def _select_game(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        game_id: str,
        now: datetime,
    ) -> ApplicationResult:
        existing = await uow.sessions.find_resumable(player, game_id)
        if existing is not None:
            self._ensure_owner(existing, player)
            self._get_pinned(existing)
            await uow.sessions.set_selected(
                player,
                existing.session_id,
                updated_at=now,
            )
            return ApplicationResult(
                (
                    Notice(
                        "session_resumed",
                        "Продолжаем сохранённую игру.",
                    ),
                )
            )

        package = self._get_latest(game_id)
        session, entry_actions = self._start_new_session(player, package, now)
        await uow.sessions.create(session)
        await uow.sessions.set_selected(
            player,
            session.session_id,
            updated_at=now,
        )
        return ApplicationResult(
            (
                GameActions(
                    session_id=session.session_id,
                    actions=entry_actions,
                ),
            )
        )

    async def _submit_game_input(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        game_input: SubmitGameInput,
        now: datetime,
        external_event_id: str | None,
    ) -> ApplicationResult:
        selected = await uow.sessions.get_selected(player)
        if selected is None:
            return ApplicationResult(
                (
                    Notice(
                        "no_selected_session",
                        "Сначала выберите игру.",
                    ),
                    await self._build_menu(uow, player),
                )
            )
        self._ensure_owner(selected, player)
        if (
            game_input.session_id is not None
            and game_input.session_id != selected.session_id
        ):
            return ApplicationResult(
                (
                    StaleInteraction(
                        expected_session_id=game_input.session_id,
                        selected_session_id=selected.session_id,
                    ),
                )
            )

        package = self._get_pinned(selected)
        result = self._engine.handle(
            package,
            selected.engine_snapshot,
            game_input.value,
            now,
        )
        completed_at = selected.completed_at
        if (
            result.session.status is SessionStatus.COMPLETED
            and completed_at is None
        ):
            completed_at = now
        updated = replace(
            selected,
            engine_snapshot=result.session,
            updated_at=now,
            completed_at=completed_at,
        )
        await uow.sessions.save(
            updated,
            expected_revision=selected.engine_snapshot.revision,
        )
        if result.scheduled:
            await uow.scheduled_actions.add(
                selected.session_id,
                result.session.revision,
                result.scheduled,
                created_at=now,
            )
        await uow.interaction_log.add(
            SessionInteractionRecord(
                session_id=selected.session_id,
                external_event_id=external_event_id,
                scene_before=selected.engine_snapshot.current_scene or None,
                scene_after=result.session.current_scene or None,
                interaction_id=result.interaction_id,
                outcome_id=result.outcome_id,
                input_kind=(
                    InteractionInputKind.TEXT
                    if isinstance(game_input.value, TextInput)
                    else InteractionInputKind.CHOICE
                ),
                input_status=result.input_status,
                invalid_reason=result.invalid_reason,
                created_at=now,
            )
        )
        return ApplicationResult(
            (
                GameActions(
                    session_id=selected.session_id,
                    actions=result.actions,
                    outcome_id=result.outcome_id,
                    interaction_id=result.interaction_id,
                    input_status=result.input_status,
                    invalid_reason=result.invalid_reason,
                ),
            )
        )

    async def _request_restart(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        session_id: str,
    ) -> ApplicationResult:
        session = await self._owned_session(uow, player, session_id)
        if session.superseded_at is not None:
            raise InvalidApplicationInteraction(
                "a superseded session cannot be restarted"
            )
        package = self._get_pinned(session)
        return ApplicationResult(
            (
                ShowRestartConfirmation(
                    session_id=session.session_id,
                    game_id=session.game_id,
                    display_title=package.manifest.display_title,
                ),
            )
        )

    async def _confirm_restart(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        session_id: str,
        now: datetime,
    ) -> ApplicationResult:
        old = await self._owned_session(
            uow,
            player,
            session_id,
            lock_owner=True,
        )
        if old.superseded_at is not None:
            raise InvalidApplicationInteraction(
                "restart was already confirmed for this session"
            )

        latest = self._get_latest(old.game_id)
        await uow.sessions.mark_superseded(
            old.session_id,
            superseded_at=now,
            expected_revision=old.engine_snapshot.revision,
        )
        await uow.scheduled_actions.cancel_for_session(
            old.session_id,
            cancelled_at=now,
        )
        await uow.outbound_deliveries.cancel_pending_for_session(
            old.session_id,
            cancelled_at=now,
        )

        new, entry_actions = self._start_new_session(player, latest, now)
        await uow.sessions.create(new)
        await uow.sessions.set_selected(
            player,
            new.session_id,
            updated_at=now,
        )
        return ApplicationResult(
            (
                GameActions(
                    session_id=new.session_id,
                    actions=entry_actions,
                ),
            )
        )

    async def _cancel_restart(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        session_id: str,
    ) -> ApplicationResult:
        session = await self._owned_session(uow, player, session_id)
        if session.superseded_at is not None:
            raise InvalidApplicationInteraction(
                "restart cannot be cancelled after confirmation"
            )
        return ApplicationResult(
            (
                Notice(
                    "restart_cancelled",
                    "Перезапуск отменён.",
                ),
            )
        )

    async def _owned_session(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        session_id: str,
        *,
        lock_owner: bool = False,
    ) -> ApplicationSession:
        session = await uow.sessions.get(
            session_id,
            lock_owner=lock_owner,
        )
        if session is None:
            raise SessionNotFound(session_id)
        self._ensure_owner(session, player)
        return session

    @staticmethod
    def _ensure_owner(
        session: ApplicationSession,
        player: PlayerContext,
    ) -> None:
        if session.player_context != player:
            raise SessionNotFound(session.session_id)

    def _get_pinned(self, session: ApplicationSession) -> GamePackage:
        return self._get_package(session.game_id, session.game_version)

    def _get_latest(self, game_id: str) -> GamePackage:
        try:
            return self._catalog.get_latest(game_id).package
        except (KeyError, ValueError) as error:
            raise GameVersionUnavailable(game_id) from error

    def _get_package(self, game_id: str, game_version: str) -> GamePackage:
        try:
            return self._catalog.get(game_id, game_version).package
        except (KeyError, ValueError) as error:
            raise GameVersionUnavailable(game_id, game_version) from error

    async def _commit_with_outbound(
        self,
        uow: ApplicationUnitOfWork,
        player: PlayerContext,
        result: ApplicationResult,
        *,
        now: datetime,
        event_id: str | None,
    ) -> ApplicationResult:
        deliveries = build_outbound_deliveries(
            player,
            result.outputs,
            source_event_id=event_id,
            now=now,
        )
        if deliveries:
            await uow.outbound_deliveries.add(deliveries)
        await uow.commit()
        return result

    def _start_new_session(
        self,
        player: PlayerContext,
        package: GamePackage,
        now: datetime,
    ) -> tuple[ApplicationSession, tuple[OutputAction, ...]]:
        snapshot = SessionSnapshot(
            session_id=self._session_id_factory(),
            game_id=package.manifest.game_id,
            game_version=package.manifest.version,
            current_scene="",
            status=SessionStatus.IN_PROGRESS,
            variables={},
            revision=0,
        )
        started = self._engine.start(package, snapshot, now)
        return (
            ApplicationSession(
                player_context=player,
                engine_snapshot=started.session,
                created_at=now,
                updated_at=now,
            ),
            started.actions,
        )
