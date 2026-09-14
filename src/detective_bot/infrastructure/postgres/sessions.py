from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from detective_bot.application.models import (
    ApplicationSession,
    Platform,
    PlayerContext,
)
from detective_bot.application.ports import SessionConflict
from detective_bot.engine.model import SessionSnapshot, SessionStatus
from detective_bot.infrastructure.postgres.models import (
    GameSessionRow,
    PlayerContextRow,
)


class PostgresSessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self,
        session_id: str,
        *,
        lock_owner: bool = False,
    ) -> ApplicationSession | None:
        statement = (
            select(GameSessionRow, PlayerContextRow)
            .join(
                PlayerContextRow,
                PlayerContextRow.id == GameSessionRow.player_context_id,
            )
            .where(GameSessionRow.id == session_id)
        )
        if lock_owner:
            statement = statement.with_for_update(of=PlayerContextRow)
        row = (await self._db.execute(statement)).one_or_none()
        return _to_application_session(*row) if row is not None else None

    async def find_resumable(
        self,
        player_context: PlayerContext,
        game_id: str,
    ) -> ApplicationSession | None:
        statement = (
            select(GameSessionRow, PlayerContextRow)
            .join(
                PlayerContextRow,
                PlayerContextRow.id == GameSessionRow.player_context_id,
            )
            .where(
                *_identity_predicates(player_context),
                GameSessionRow.game_id == game_id,
                GameSessionRow.lifecycle_status == "in_progress",
            )
        )
        row = (await self._db.execute(statement)).one_or_none()
        return _to_application_session(*row) if row is not None else None

    async def list_resumable(
        self,
        player_context: PlayerContext,
    ) -> tuple[ApplicationSession, ...]:
        statement = (
            select(GameSessionRow, PlayerContextRow)
            .join(
                PlayerContextRow,
                PlayerContextRow.id == GameSessionRow.player_context_id,
            )
            .where(
                *_identity_predicates(player_context),
                GameSessionRow.lifecycle_status == "in_progress",
            )
            .order_by(GameSessionRow.game_id, GameSessionRow.started_at)
        )
        rows = (await self._db.execute(statement)).all()
        return tuple(_to_application_session(*row) for row in rows)

    async def create(self, session: ApplicationSession) -> None:
        player_id = await get_or_create_player_context(
            self._db,
            session.player_context,
            now=session.created_at,
        )
        statement = insert(GameSessionRow).values(
            id=session.session_id,
            player_context_id=player_id,
            game_id=session.game_id,
            game_version=session.game_version,
            lifecycle_status=session.status.value,
            current_scene=session.engine_snapshot.current_scene,
            engine_status=session.engine_snapshot.status.value,
            variables=dict(session.engine_snapshot.variables),
            revision=session.engine_snapshot.revision,
            started_at=session.created_at,
            updated_at=session.updated_at,
            completed_at=session.completed_at,
            superseded_at=session.superseded_at,
        )
        try:
            await self._db.execute(statement)
        except IntegrityError as error:
            raise SessionConflict(
                f"session conflicts with persisted lifecycle: {session.session_id}"
            ) from error

    async def save(
        self,
        session: ApplicationSession,
        *,
        expected_revision: int,
    ) -> None:
        statement = (
            update(GameSessionRow)
            .where(
                GameSessionRow.id == session.session_id,
                GameSessionRow.revision == expected_revision,
            )
            .values(
                lifecycle_status=session.status.value,
                current_scene=session.engine_snapshot.current_scene,
                engine_status=session.engine_snapshot.status.value,
                variables=dict(session.engine_snapshot.variables),
                revision=session.engine_snapshot.revision,
                updated_at=session.updated_at,
                completed_at=session.completed_at,
                superseded_at=session.superseded_at,
            )
        )
        result = await self._db.execute(statement)
        if result.rowcount != 1:
            raise SessionConflict(
                f"session revision conflict: {session.session_id} "
                f"expected {expected_revision}"
            )

    async def mark_superseded(
        self,
        session_id: str,
        *,
        superseded_at: datetime,
        expected_revision: int,
    ) -> ApplicationSession:
        statement = (
            update(GameSessionRow)
            .where(
                GameSessionRow.id == session_id,
                GameSessionRow.revision == expected_revision,
                GameSessionRow.lifecycle_status != "superseded",
            )
            .values(
                lifecycle_status="superseded",
                superseded_at=superseded_at,
                updated_at=superseded_at,
            )
            .returning(GameSessionRow)
        )
        game_session = (await self._db.execute(statement)).scalar_one_or_none()
        if game_session is None:
            raise SessionConflict(
                f"session revision conflict: {session_id} "
                f"expected {expected_revision}"
            )
        player = await self._db.get(
            PlayerContextRow,
            game_session.player_context_id,
        )
        if player is None:
            raise SessionConflict("session owner does not exist")
        return _to_application_session(game_session, player)

    async def get_selected(
        self,
        player_context: PlayerContext,
    ) -> ApplicationSession | None:
        player_statement = (
            select(PlayerContextRow)
            .where(*_identity_predicates(player_context))
            .with_for_update()
        )
        player = (await self._db.execute(player_statement)).scalar_one_or_none()
        if player is None or player.selected_session_id is None:
            return None
        game_session = await self._db.get(
            GameSessionRow,
            player.selected_session_id,
        )
        if game_session is None:
            raise SessionConflict("selected session does not exist")
        return _to_application_session(game_session, player)

    async def set_selected(
        self,
        player_context: PlayerContext,
        session_id: str | None,
        *,
        updated_at: datetime,
    ) -> None:
        player_id = await get_or_create_player_context(
            self._db,
            player_context,
            now=updated_at,
            for_update=True,
        )
        if session_id is not None:
            owner_id = (
                await self._db.execute(
                    select(GameSessionRow.player_context_id).where(
                        GameSessionRow.id == session_id
                    )
                )
            ).scalar_one_or_none()
            if owner_id != player_id:
                raise SessionConflict(
                    "selected session is missing or belongs to another player"
                )
        await self._db.execute(
            update(PlayerContextRow)
            .where(PlayerContextRow.id == player_id)
            .values(
                selected_session_id=session_id,
                updated_at=updated_at,
            )
        )


async def get_or_create_player_context(
    db: AsyncSession,
    player_context: PlayerContext,
    *,
    now: datetime,
    for_update: bool = False,
) -> int:
    await db.execute(
        insert(PlayerContextRow)
        .values(
            platform=player_context.platform.value,
            external_user_id=player_context.external_user_id,
            external_chat_id=player_context.external_chat_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=(
                PlayerContextRow.platform,
                PlayerContextRow.external_user_id,
                PlayerContextRow.external_chat_id,
            )
        )
    )
    statement = select(PlayerContextRow.id).where(
        *_identity_predicates(player_context)
    )
    if for_update:
        statement = statement.with_for_update()
    player_id = (await db.execute(statement)).scalar_one()
    return player_id


def _identity_predicates(player_context: PlayerContext) -> tuple:
    return (
        PlayerContextRow.platform == player_context.platform.value,
        PlayerContextRow.external_user_id == player_context.external_user_id,
        PlayerContextRow.external_chat_id == player_context.external_chat_id,
    )


def _to_application_session(
    game_session: GameSessionRow,
    player: PlayerContextRow,
) -> ApplicationSession:
    return ApplicationSession(
        player_context=PlayerContext(
            platform=Platform(player.platform),
            external_user_id=player.external_user_id,
            external_chat_id=player.external_chat_id,
        ),
        engine_snapshot=SessionSnapshot(
            session_id=game_session.id,
            game_id=game_session.game_id,
            game_version=game_session.game_version,
            current_scene=game_session.current_scene,
            status=SessionStatus(game_session.engine_status),
            variables=game_session.variables,
            revision=game_session.revision,
        ),
        created_at=game_session.started_at,
        updated_at=game_session.updated_at,
        completed_at=game_session.completed_at,
        superseded_at=game_session.superseded_at,
    )
