from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from vkbottle import Callback, Keyboard

from detective_bot.adapters.media import ResolvedMedia, sha256_file
from detective_bot.adapters.telegram.callback_data import (
    CancelRestartCallback,
    ConfirmRestartCallback,
    GameChoiceCallback,
    SelectGameCallback,
)
from detective_bot.adapters.vk.callback_data import pack_payload
from detective_bot.adapters.vk.inbound import STALE_BUTTON_NOTICE
from detective_bot.adapters.vk.sender import StaleVkAttachment, VkSender
from detective_bot.application.models import (
    ApplicationOutput,
    ApplicationResult,
    DuplicateInteraction,
    GameActions,
    MenuEntryState,
    Notice,
    ShowGameMenu,
    ShowRestartConfirmation,
    StaleInteraction,
)
from detective_bot.application.outbound import OutboundSemantic
from detective_bot.application.ports import Clock, UnitOfWorkFactory
from detective_bot.engine.model import (
    ChoiceActionOption,
    ChoiceInputSpec,
    ChoicesAction,
    InputStatus,
    MediaAction,
    TextAction,
)
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog


class MediaResolver(Protocol):
    async def resolve(self, session_id: str, asset_id: str) -> ResolvedMedia: ...


class VkMediaCache(Protocol):
    async def get(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> str | None: ...

    async def put(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
        attachment: str,
        *,
        now: datetime,
    ) -> None: ...

    async def delete(
        self,
        community_id: str,
        asset_sha256: str,
        media_kind: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class VkMediaPolicy:
    document_asset_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _SessionRenderContext:
    revision: int
    options: dict[str, tuple[ChoiceActionOption, ...]]


class VkRenderer:
    def __init__(
        self,
        sender: VkSender,
        resolver: MediaResolver,
        policy: VkMediaPolicy,
        catalog: FileSystemGameCatalog | None = None,
        uow_factory: UnitOfWorkFactory | None = None,
        media_cache: VkMediaCache | None = None,
        community_id: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._sender = sender
        self._resolver = resolver
        self._policy = policy
        self._catalog = catalog
        self._uow_factory = uow_factory
        self._media_cache = media_cache
        self._community_id = community_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def render(self, peer_id: int, result: ApplicationResult) -> None:
        for output in result.outputs:
            await self._render_output(peer_id, output)

    async def render_semantic(
        self,
        chat_id: int,
        item: OutboundSemantic,
        *,
        session_id: str | None,
    ) -> None:
        if isinstance(item, (TextAction, MediaAction, ChoicesAction)):
            await self._render_engine_action(chat_id, item, session_id)
            return
        await self._render_output(chat_id, item)

    async def send_notice(self, peer_id: int, text: str) -> None:
        await self._sender.send_text(peer_id, text)

    async def _render_output(self, peer_id: int, output: ApplicationOutput) -> None:
        if isinstance(output, DuplicateInteraction):
            return
        if isinstance(output, StaleInteraction):
            await self._sender.send_text(peer_id, STALE_BUTTON_NOTICE)
            return
        if isinstance(output, Notice):
            await self._sender.send_text(peer_id, output.text)
            return
        if isinstance(output, ShowGameMenu):
            await self._render_menu(peer_id, output)
            return
        if isinstance(output, ShowRestartConfirmation):
            await self._render_restart(peer_id, output)
            return
        if isinstance(output, GameActions):
            await self._render_game_actions(peer_id, output)
            return

    async def _render_menu(self, peer_id: int, menu: ShowGameMenu) -> None:
        keyboard = Keyboard(inline=True)
        for game in menu.games:
            label = (
                f"Продолжить: {game.display_title}"
                if game.state is MenuEntryState.CONTINUE
                else game.display_title
            )
            keyboard.add(
                Callback(label, pack_payload(SelectGameCallback(game_id=game.game_id)))
            )
            keyboard.row()
        await self._sender.send_text(
            peer_id,
            "Выберите расследование:",
            keyboard=keyboard.get_json(),
        )

    async def _render_restart(
        self,
        peer_id: int,
        confirmation: ShowRestartConfirmation,
    ) -> None:
        keyboard = Keyboard(inline=True)
        keyboard.add(
            Callback("Да", pack_payload(ConfirmRestartCallback(confirmation.session_id)))
        )
        keyboard.add(
            Callback("Нет", pack_payload(CancelRestartCallback(confirmation.session_id)))
        )
        await self._sender.send_text(
            peer_id,
            f"Начать {confirmation.display_title} заново?",
            keyboard=keyboard.get_json(),
        )

    async def _render_game_actions(
        self,
        peer_id: int,
        output: GameActions,
    ) -> None:
        if output.input_status is InputStatus.STALE:
            await self._sender.send_text(peer_id, STALE_BUTTON_NOTICE)
            return
        for action in output.actions:
            await self._render_engine_action(peer_id, action, output.session_id)

    async def _render_engine_action(
        self,
        peer_id: int,
        action: TextAction | MediaAction | ChoicesAction,
        session_id: str | None,
    ) -> None:
        if isinstance(action, TextAction):
            await self._sender.send_text(peer_id, action.text)
            return
        if isinstance(action, MediaAction):
            await self._render_media(peer_id, session_id or "", action)
            return
        context = await self._session_context(session_id or "")
        await self._render_choices(peer_id, session_id or "", action, context)

    async def _render_media(
        self,
        peer_id: int,
        session_id: str,
        action: MediaAction,
    ) -> None:
        media = await self._resolver.resolve(session_id, action.asset)
        kind = self._media_kind(media)
        method = self._media_method(kind)
        digest = sha256_file(media.path)
        cached = await self._cached_attachment(digest, kind)
        try:
            attachment = await method(
                peer_id,
                media.path,
                action.caption,
                None,
                file_id=cached,
            )
        except StaleVkAttachment:
            await self._drop_cached_attachment(digest, kind)
            attachment = await method(
                peer_id,
                media.path,
                action.caption,
                None,
                file_id=None,
            )
        if attachment:
            await self._store_cached_attachment(digest, kind, attachment)

    def _media_kind(self, media: ResolvedMedia) -> str:
        if (
            media.asset_id in self._policy.document_asset_ids
            or media.asset_type == "document"
        ):
            return "document"
        if media.asset_type == "audio":
            return "audio"
        return "photo"

    def _media_method(self, kind: str):
        if kind == "document":
            return self._sender.send_document
        if kind == "audio":
            return self._sender.send_audio
        return self._sender.send_photo

    async def _cached_attachment(self, digest: str, kind: str) -> str | None:
        if self._media_cache is None or self._community_id is None:
            return None
        return await self._media_cache.get(self._community_id, digest, kind)

    async def _store_cached_attachment(
        self,
        digest: str,
        kind: str,
        attachment: str,
    ) -> None:
        if self._media_cache is None or self._community_id is None:
            return
        await self._media_cache.put(
            self._community_id,
            digest,
            kind,
            attachment,
            now=self._clock(),
        )

    async def _drop_cached_attachment(self, digest: str, kind: str) -> None:
        if self._media_cache is None or self._community_id is None:
            return
        await self._media_cache.delete(self._community_id, digest, kind)

    async def _render_choices(
        self,
        peer_id: int,
        session_id: str,
        action: ChoicesAction,
        context: _SessionRenderContext,
    ) -> None:
        options = action.options or context.options.get(action.interaction, ())
        keyboard = Keyboard(inline=True)
        for option in options:
            keyboard.add(
                Callback(
                    option.label,
                    pack_payload(
                        GameChoiceCallback(
                            session_id=session_id,
                            revision=context.revision,
                            interaction_id=action.interaction,
                            value=option.value,
                        )
                    ),
                )
            )
            keyboard.row()
        await self._sender.send_text(
            peer_id,
            action.text,
            keyboard=keyboard.get_json() if options else None,
        )

    async def _session_context(self, session_id: str) -> _SessionRenderContext:
        if self._catalog is None or self._uow_factory is None:
            return _SessionRenderContext(revision=0, options={})
        async with self._uow_factory() as uow:
            session = await uow.sessions.get(session_id)
        if session is None:
            return _SessionRenderContext(revision=0, options={})
        loaded = self._catalog.get(session.game_id, session.game_version)
        scene = loaded.package.definition.scenes.get(
            session.engine_snapshot.current_scene
        )
        options: dict[str, tuple[ChoiceActionOption, ...]] = {}
        if scene is not None:
            for interaction in scene.interactions:
                if isinstance(interaction.input, ChoiceInputSpec):
                    options[interaction.id] = tuple(
                        ChoiceActionOption(value=value, label=option.label)
                        for value, option in interaction.input.options.items()
                    )
        return _SessionRenderContext(
            revision=session.engine_snapshot.revision,
            options=options,
        )
