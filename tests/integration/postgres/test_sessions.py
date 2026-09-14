from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest

from detective_bot.application.models import (
    ApplicationSession,
    ApplicationSessionStatus,
    Platform,
    PlayerContext,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.engine.model import SessionStatus
from detective_bot.infrastructure.postgres.uow import (
    PostgresUnitOfWorkFactory,
)
from tests.integration.postgres.conftest import NOW


PLAYER = PlayerContext(Platform.TELEGRAM, "user-1", "chat-1")
OTHER_PLAYER = PlayerContext(Platform.VK, "user-2", "chat-2")


async def test_session_crud_lifecycle_and_jsonb_round_trip(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    created = session_builder(
        session_id="session-1",
        player=PLAYER,
        variables={"flag": True, "count": 7, "label": "value"},
    )
    async with uow_factory() as uow:
        await uow.sessions.create(created)
        await uow.sessions.set_selected(
            PLAYER,
            created.session_id,
            updated_at=NOW,
        )
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.sessions.get("session-1")
        assert loaded is not None
        assert dict(loaded.engine_snapshot.variables) == {
            "flag": True,
            "count": 7,
            "label": "value",
        }
        assert await uow.sessions.find_resumable(PLAYER, "lora_dein") == loaded
        assert await uow.sessions.list_resumable(PLAYER) == (loaded,)
        assert await uow.sessions.get_selected(PLAYER) == loaded

        completed_at = NOW + timedelta(minutes=5)
        completed = replace(
            loaded,
            engine_snapshot=loaded.engine_snapshot.model_copy(
                update={
                    "status": SessionStatus.COMPLETED,
                    "revision": 2,
                }
            ),
            updated_at=completed_at,
            completed_at=completed_at,
        )
        await uow.sessions.save(completed, expected_revision=1)
        await uow.commit()

    async with uow_factory() as uow:
        completed = await uow.sessions.get("session-1")
        assert completed is not None
        assert completed.status is ApplicationSessionStatus.COMPLETED
        assert await uow.sessions.find_resumable(PLAYER, "lora_dein") is None
        superseded = await uow.sessions.mark_superseded(
            "session-1",
            superseded_at=NOW + timedelta(minutes=6),
            expected_revision=2,
        )
        assert superseded.status is ApplicationSessionStatus.SUPERSEDED
        await uow.commit()

    async with uow_factory() as uow:
        persisted = await uow.sessions.get("session-1")
        assert persisted is not None
        assert persisted.status is ApplicationSessionStatus.SUPERSEDED


async def test_optimistic_revision_conflict_uses_two_transactions(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    async with uow_factory() as seed:
        await seed.sessions.create(
            session_builder(session_id="session-1", player=PLAYER)
        )
        await seed.commit()

    async with uow_factory() as first, uow_factory() as second:
        first_copy = await first.sessions.get("session-1")
        second_copy = await second.sessions.get("session-1")
        assert first_copy is not None and second_copy is not None
        assert first_copy.engine_snapshot.revision == 1
        assert second_copy.engine_snapshot.revision == 1

        first_update = replace(
            first_copy,
            engine_snapshot=first_copy.engine_snapshot.model_copy(
                update={"revision": 2, "current_scene": "lora_scene2"}
            ),
        )
        await first.sessions.save(first_update, expected_revision=1)
        await first.commit()

        second_update = replace(
            second_copy,
            engine_snapshot=second_copy.engine_snapshot.model_copy(
                update={"revision": 2, "current_scene": "lora_scene3"}
            ),
        )
        with pytest.raises(SessionConflict):
            await second.sessions.save(second_update, expected_revision=1)


async def test_partial_unique_constraint_blocks_concurrent_resumable_runs(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    async with uow_factory() as seed:
        first_session = session_builder(session_id="session-1", player=PLAYER)
        await seed.sessions.create(first_session)
        await seed.sessions.mark_superseded(
            first_session.session_id,
            superseded_at=NOW,
            expected_revision=1,
        )
        await seed.commit()

    async with uow_factory() as first, uow_factory() as second:
        await first.sessions.create(
            session_builder(session_id="session-a", player=PLAYER)
        )
        blocked_insert = asyncio.create_task(
            second.sessions.create(
                session_builder(session_id="session-b", player=PLAYER)
            )
        )
        await asyncio.sleep(0.1)
        assert not blocked_insert.done()
        await first.commit()

        with pytest.raises(SessionConflict):
            await blocked_insert


async def test_selected_session_must_belong_to_player(
    uow_factory: PostgresUnitOfWorkFactory,
    session_builder: Callable[..., ApplicationSession],
) -> None:
    async with uow_factory() as uow:
        own = session_builder(session_id="own", player=PLAYER)
        foreign = session_builder(session_id="foreign", player=OTHER_PLAYER)
        await uow.sessions.create(own)
        await uow.sessions.create(foreign)
        await uow.commit()

    async with uow_factory() as uow:
        with pytest.raises(SessionConflict):
            await uow.sessions.set_selected(
                PLAYER,
                "foreign",
                updated_at=NOW,
            )
