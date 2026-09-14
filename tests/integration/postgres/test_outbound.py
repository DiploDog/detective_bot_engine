from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from detective_bot.application.models import (
    ApplicationSession,
    ConfirmRestart,
    GameActions,
    MenuEntryState,
    MenuGame,
    Notice,
    SelectGame,
    ShowGameMenu,
    ShowRestartConfirmation,
    SubmitGameInput,
)
from detective_bot.application.outbound import (
    build_outbound_deliveries,
    deserialize_action_payload,
)
from detective_bot.engine.model import (
    ChoiceActionOption,
    ChoicesAction,
    MediaAction,
    SessionSnapshot,
    SessionStatus,
    TextAction,
    TextInput,
)
from detective_bot.infrastructure.postgres.models import (
    OutboundDeliveryRow,
    ProcessedEventRow,
    SessionInteractionRow,
)
from detective_bot.infrastructure.postgres.uow import PostgresUnitOfWorkFactory
from tests.integration.postgres.conftest import NOW
from tests.integration.postgres.test_application_transactions import (
    PLAYER,
    FailCommitUnitOfWorkFactory,
    handle,
    make_service,
)


async def load_outbound(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_event_id: str | None = None,
) -> list[OutboundDeliveryRow]:
    async with session_factory() as db:
        statement = select(OutboundDeliveryRow).order_by(
            OutboundDeliveryRow.sequence_no,
            OutboundDeliveryRow.id,
        )
        if source_event_id is not None:
            statement = statement.where(
                OutboundDeliveryRow.source_event_id == source_event_id
            )
        return list(await db.scalars(statement))


async def test_game_interaction_commits_session_event_log_and_outbound(
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

    async with uow_factory() as uow:
        session = await uow.sessions.get("session-1")
        assert session is not None
        assert session.engine_snapshot.current_scene == "lora_scene2"
    async with session_factory() as db:
        assert await db.scalar(
            select(func.count())
            .select_from(ProcessedEventRow)
            .where(ProcessedEventRow.external_event_id == "lora-scene-1")
        ) == 1
        assert await db.scalar(
            select(func.count())
            .select_from(SessionInteractionRow)
            .where(SessionInteractionRow.external_event_id == "lora-scene-1")
        ) == 1
        outbound = list(
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.source_event_id == "lora-scene-1"
                )
            )
        )
        assert outbound
        assert all(row.status == "pending" for row in outbound)
        assert {row.action_payload["type"] for row in outbound} <= {
            "text",
            "media",
            "choices",
        }


async def test_rollback_removes_session_event_log_and_outbound(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(FailCommitUnitOfWorkFactory(session_factory))
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await handle(service, SelectGame("lora_dein"), "failed-select")

    async with PostgresUnitOfWorkFactory(session_factory)() as verify:
        assert await verify.sessions.get("session-1") is None
    async with session_factory() as db:
        assert await db.scalar(
            select(func.count()).select_from(ProcessedEventRow)
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(SessionInteractionRow)
        ) == 0
        assert await db.scalar(
            select(func.count()).select_from(OutboundDeliveryRow)
        ) == 0


async def test_duplicate_event_does_not_create_second_outbound_batch(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    first = await handle(service, SelectGame("lora_dein"), "select-once")
    duplicate = await handle(service, SelectGame("lora_dein"), "select-once")

    assert first.outputs
    assert duplicate.outputs[0].__class__.__name__ == "DuplicateInteraction"
    rows = await load_outbound(session_factory, source_event_id="select-once")
    assert rows
    assert [row.sequence_no for row in rows] == list(range(len(rows)))
    async with session_factory() as db:
        assert await db.scalar(
            select(func.count())
            .select_from(OutboundDeliveryRow)
            .where(OutboundDeliveryRow.source_event_id == "select-once")
        ) == len(rows)


async def test_outbound_sequence_preserves_semantic_action_order(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("killing_margo"), "margo-select")
    async with uow_factory() as uow:
        selected = await uow.sessions.get_selected(PLAYER)
        assert selected is not None
        await uow.sessions.save(
            replace(
                selected,
                engine_snapshot=selected.engine_snapshot.model_copy(
                    update={"current_scene": "margo_q9", "revision": 20}
                ),
            ),
            expected_revision=1,
        )
        await uow.commit()

    result = await handle(
        service,
        SubmitGameInput(TextInput(text="31,33")),
        "margo-q9",
    )
    actions = result.outputs[0].actions  # type: ignore[attr-defined]
    assert len(actions) >= 3
    rows = await load_outbound(session_factory, source_event_id="margo-q9")
    assert [row.sequence_no for row in rows] == list(range(len(rows)))
    assert [row.sequence_no for row in rows[:3]] == [0, 1, 2]
    restored = [deserialize_action_payload(row.action_payload) for row in rows]
    assert restored == list(actions)


async def test_restart_cancels_old_pending_outbound_and_enqueues_new_start(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = make_service(uow_factory)
    await handle(service, SelectGame("lora_dein"), "select-old")
    await handle(
        service,
        SubmitGameInput(TextInput(text="1,3")),
        "progress-old",
    )
    async with session_factory() as db:
        delivered = (
            await db.scalars(
                select(OutboundDeliveryRow)
                .where(OutboundDeliveryRow.source_event_id == "select-old")
                .order_by(OutboundDeliveryRow.sequence_no)
                .limit(1)
            )
        ).one()
        await db.execute(
            update(OutboundDeliveryRow)
            .where(OutboundDeliveryRow.id == delivered.id)
            .values(status="delivered", delivered_at=NOW)
        )
        await db.commit()
        delivered_id = delivered.id

    await handle(service, ConfirmRestart("session-1"), "restart-old")

    async with uow_factory() as uow:
        old = await uow.sessions.get("session-1")
        new = await uow.sessions.get("session-2")
        selected = await uow.sessions.get_selected(PLAYER)
        assert old is not None and old.superseded_at == NOW
        assert new is not None
        assert selected is not None and selected.session_id == "session-2"
    async with session_factory() as db:
        old_rows = list(
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.session_id == "session-1"
                )
            )
        )
        statuses = {row.id: row.status for row in old_rows}
        assert statuses[delivered_id] == "delivered"
        assert all(
            row.status == "cancelled"
            for row in old_rows
            if row.id != delivered_id
        )
        new_rows = list(
            await db.scalars(
                select(OutboundDeliveryRow).where(
                    OutboundDeliveryRow.source_event_id == "restart-old"
                )
            )
        )
        assert new_rows
        assert all(row.status == "pending" for row in new_rows)
        assert all(row.session_id == "session-2" for row in new_rows)


async def test_postgres_round_trip_serializes_semantic_output_types(
    uow_factory: PostgresUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    game_actions = GameActions(
        session_id="session-roundtrip",
        actions=(
            TextAction(type="text", text="текст"),
            MediaAction(
                type="media",
                asset="phone_recording",
                caption="запись",
            ),
            ChoicesAction(
                type="choices",
                interaction="hint_q1",
                text="Нужна подсказка?",
                options=(
                    ChoiceActionOption(value="yes", label="Да"),
                    ChoiceActionOption(value="no", label="Нет"),
                ),
            ),
        ),
    )
    outputs = (
        Notice("session_resumed", "Продолжаем сохранённую игру."),
        ShowGameMenu(
            (
                MenuGame(
                    game_id="lora_dein",
                    game_version="1.0.0",
                    display_title="Лора Дейн",
                    state=MenuEntryState.NEW,
                ),
            )
        ),
        ShowRestartConfirmation(
            session_id="session-roundtrip",
            game_id="lora_dein",
            display_title="Лора Дейн",
        ),
        game_actions,
    )
    async with uow_factory() as uow:
        await uow.sessions.create(
            ApplicationSession(
                player_context=PLAYER,
                engine_snapshot=SessionSnapshot(
                    session_id="session-roundtrip",
                    game_id="lora_dein",
                    game_version="1.0.0",
                    current_scene="lora_scene1",
                    status=SessionStatus.IN_PROGRESS,
                    variables={},
                    revision=1,
                ),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await uow.outbound_deliveries.add(
            build_outbound_deliveries(
                PLAYER,
                outputs,
                source_event_id="round-trip",
                now=NOW,
            )
        )
        await uow.commit()

    rows = await load_outbound(session_factory, source_event_id="round-trip")
    assert [row.sequence_no for row in rows] == [0, 1, 2, 3, 4, 5]
    restored = [deserialize_action_payload(row.action_payload) for row in rows]
    assert restored[0] == outputs[0]
    assert restored[1] == outputs[1]
    assert restored[2] == outputs[2]
    assert restored[3:] == list(game_actions.actions)
    assert [row.action_payload["type"] for row in rows] == [
        "notice",
        "show_game_menu",
        "show_restart_confirmation",
        "text",
        "media",
        "choices",
    ]
    assert all("callback_data" not in str(row.action_payload) for row in rows)
    assert all("InlineKeyboard" not in str(row.action_payload) for row in rows)
