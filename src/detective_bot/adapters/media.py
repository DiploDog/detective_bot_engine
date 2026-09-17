from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from detective_bot.application.ports import UnitOfWorkFactory
from detective_bot.infrastructure.game_catalog import FileSystemGameCatalog


class MediaResolutionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedMedia:
    asset_id: str
    asset_type: str
    path: Path


class CatalogMediaResolver:
    def __init__(
        self,
        catalog: FileSystemGameCatalog,
        uow_factory: UnitOfWorkFactory,
        *,
        platform: str | None = None,
    ) -> None:
        self._catalog = catalog
        self._uow_factory = uow_factory
        self._platform = platform

    async def resolve(self, session_id: str, asset_id: str) -> ResolvedMedia:
        async with self._uow_factory() as uow:
            session = await uow.sessions.get(session_id)
        if session is None:
            raise MediaResolutionError(f"session is missing: {session_id}")
        loaded = self._catalog.get(session.game_id, session.game_version)
        path = loaded.asset_paths.get(asset_id)
        asset = loaded.package.manifest.assets.get(asset_id)
        if path is None or asset is None:
            raise MediaResolutionError(f"asset is not installed: {asset_id}")
        if self._platform is not None:
            path = loaded.asset_variant_paths.get(asset_id, {}).get(
                self._platform,
                path,
            )
        return ResolvedMedia(
            asset_id=asset_id,
            asset_type=asset.type,
            path=path,
        )
