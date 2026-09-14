from __future__ import annotations

from detective_bot.adapters.media import (
    CatalogMediaResolver,
    MediaResolutionError,
    ResolvedMedia,
    sha256_file,
)


def bot_id_from_token(token: str) -> str:
    return token.split(":", 1)[0]


__all__ = [
    "CatalogMediaResolver",
    "MediaResolutionError",
    "ResolvedMedia",
    "bot_id_from_token",
    "sha256_file",
]
