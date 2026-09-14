from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from itertools import count

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.application.models import (
    ApplicationSession,
    ApplicationSessionStatus,
    ConfirmRestart,
    IncomingInteraction,
    OpenMenu,
    Platform,
    PlayerContext,
    SelectGame,
    SubmitGameInput,
)
from detective_bot.application.service import ApplicationService
from detective_bot.engine.model import ScheduledActionRequest, TextInput
from detective_bot.engine.runner import GameEngine
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog
from detective_bot.infrastructure.postgres.models import (
    ProcessedEventRow,
    ScheduledActionRow,
    SessionInteractionRow,
)
from detective_bot.infrastructure.postgres.uow import (
    PostgresUnitOfWork,
    PostgresUnitOfWorkFactory,
)
from tests.integration.postgres.conftest import NOW, ROOT


PLAYER = PlayerContext(Platform.TELEGRAM, "app-user", "app-chat")


def make_service(
    uow_factory,
    *,
    first_id: int = 1,
) -> ApplicationService:
    sequence = count(first_id)
    return ApplicationService(
        catalog=FileSystemGameCatalog(ROOT / "games"),
        uow_factory=uow_factory,
        engine=GameEngine(),
        clock=lambda: NOW,
        session_id_factory=lambda: f"session-{next(sequence)}",
    )


async def handle(
    service: ApplicationService,
    action,
    event_id: str,
):
    return await service.handle(
        IncomingInteraction(
            player_context=PLAYER,
            action=action,
            external_event_id=event_id,
        )
    )


async def test_margo_q9_is_atomic_through_real_application_service(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("killing_margo"), "select-margo")
    async with uow_factory() as uow:
        selected = await uow.sessions.get_selected(PLAYER)
        assert selected is not None
        at_q9 = replace(
            selected,
            engine_snapshot=selected.engine_snapshot.model_copy(
                update={"current_scene": "margo_q9", "revision": 20}
            ),
        )
        await uow.sessions.save(at_q9, expected_revision=1)
        await uow.commit()

    await handle(
        service,
        SubmitGameInput(TextInput(text="31,33")),
        "margo-q9",
    )

    async with uow_factory() as uow:
        persisted = await uow.sessions.get("session-1")
        assert persisted is not None
        assert persisted.engine_snapshot.current_scene == "margo_articles"
        assert persisted.engine_snapshot.revision == 21
    async with session_factory() as db:
        scheduled = (
            await db.scalars(select(ScheduledActionRow))
        ).one()
        assert scheduled.template_id == "reveal_articles"
        assert scheduled.origin_revision == 21
        assert scheduled.due_at == NOW + timedelta(seconds=300)
        assert scheduled.status == "pending"
        logged = (
            await db.scalars(select(SessionInteractionRow))
        ).one()
        assert logged.external_event_id == "margo-q9"
        assert logged.scene_before == "margo_q9"
        assert logged.scene_after == "margo_articles"
        assert logged.outcome_id == "q9_correct"


async def test_lora_flow_persists_completion_and_interaction_log(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("lora_dein"), "lora-select")
    await handle(
        service,
        SubmitGameInput(TextInput(text="1,3")),
        "lora-scene-1",
    )
    await handle(
        service,
        SubmitGameInput(TextInput(text="1,2")),
        "lora-scene-2",
    )
    await handle(
        service,
        SubmitGameInput(TextInput(text="6")),
        "lora-scene-3",
    )

    async with uow_factory() as uow:
        completed = await uow.sessions.get("session-1")
        assert completed is not None
        assert completed.status is ApplicationSessionStatus.COMPLETED
        assert completed.completed_at == NOW
    async with session_factory() as db:
        assert await db.scalar(
            select(func.count()).select_from(SessionInteractionRow)
        ) == 3


async def test_switch_games_survives_new_database_sessions(
    uow_factory: PostgresUnitOfWorkFactory,
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("killing_margo"), "margo-select")
    await handle(
        service,
        SubmitGameInput(TextInput(text="нет")),
        "margo-progress",
    )
    await handle(service, OpenMenu(), "menu-1")
    await handle(service, SelectGame("lora_dein"), "lora-select")
    await handle(
        service,
        SubmitGameInput(TextInput(text="1,3")),
        "lora-progress",
    )
    await handle(service, OpenMenu(), "menu-2")
    await handle(service, SelectGame("killing_margo"), "margo-resume")

    async with uow_factory() as fresh:
        selected = await fresh.sessions.get_selected(PLAYER)
        margo = await fresh.sessions.get("session-1")
        lora = await fresh.sessions.get("session-2")
        assert selected is not None and selected.session_id == "session-1"
        assert margo is not None
        assert margo.engine_snapshot.current_scene == "margo_q2"
        assert lora is not None
        assert lora.engine_snapshot.current_scene == "lora_scene2"


class FailCreateRepository:
    def __init__(self, wrapped, failing_session_id: str) -> None:
        self._wrapped = wrapped
        self._failing_session_id = failing_session_id

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)

    async def create(self, session: ApplicationSession) -> None:
        if session.session_id == self._failing_session_id:
            raise RuntimeError("injected create failure")
        await self._wrapped.create(session)


class FailRestartUnitOfWork(PostgresUnitOfWork):
    async def __aenter__(self):
        await super().__aenter__()
        self.sessions = FailCreateRepository(self.sessions, "session-2")
        return self


class FailRestartUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(self) -> FailRestartUnitOfWork:
        return FailRestartUnitOfWork(self._session_factory)


async def test_restart_failure_rolls_back_entire_transaction(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("lora_dein"), "select-old")
    async with uow_factory() as seed:
        await seed.scheduled_actions.add(
            "session-1",
            1,
            (
                ScheduledActionRequest(
                    template_id="reminder",
                    due_at=NOW,
                    idempotency_key="reminder",
                ),
            ),
            created_at=NOW,
        )
        await seed.commit()

    failing_service = make_service(
        FailRestartUnitOfWorkFactory(session_factory),
        first_id=2,
    )
    with pytest.raises(RuntimeError, match="injected create failure"):
        await handle(
            failing_service,
            ConfirmRestart("session-1"),
            "restart-old",
        )

    async with uow_factory() as verify:
        old = await verify.sessions.get("session-1")
        selected = await verify.sessions.get_selected(PLAYER)
        assert old is not None
        assert old.status is ApplicationSessionStatus.IN_PROGRESS
        assert old.superseded_at is None
        assert selected is not None and selected.session_id == "session-1"
        assert await verify.sessions.get("session-2") is None
    async with session_factory() as db:
        scheduled = (
            await db.scalars(select(ScheduledActionRow))
        ).one()
        assert scheduled.status == "pending"
        assert await db.scalar(
            select(func.count())
            .select_from(ProcessedEventRow)
            .where(ProcessedEventRow.external_event_id == "restart-old")
        ) == 0


class FailCommitUnitOfWork(PostgresUnitOfWork):
    async def commit(self) -> None:
        raise RuntimeError("injected commit failure")


class FailCommitUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(self) -> FailCommitUnitOfWork:
        return FailCommitUnitOfWork(self._session_factory)


async def test_interaction_failure_rolls_back_state_event_log_and_schedule(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("lora_dein"), "seed-lora")
    failing_service = make_service(FailCommitUnitOfWorkFactory(session_factory))

    with pytest.raises(RuntimeError, match="injected commit failure"):
        await handle(
            failing_service,
            SubmitGameInput(TextInput(text="1,3")),
            "failed-input",
        )

    async with uow_factory() as verify:
        unchanged = await verify.sessions.get("session-1")
        assert unchanged is not None
        assert unchanged.engine_snapshot.current_scene == "lora_scene1"
        assert unchanged.engine_snapshot.revision == 1
    async with session_factory() as db:
        assert await db.scalar(
            select(func.count())
            .select_from(ProcessedEventRow)
            .where(ProcessedEventRow.external_event_id == "failed-input")
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(SessionInteractionRow)
        ) == 0
