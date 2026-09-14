from __future__ import annotations

import asyncio
import logging
import sys

from detective_bot.adapters.vk.runtime import VkRuntime
from detective_bot.infrastructure.settings import SettingsError, load_vk_settings


logger = logging.getLogger(__name__)


def main() -> None:
    try:
        settings = load_vk_settings()
    except SettingsError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
    runtime = VkRuntime(settings)
    runtime.setup()
    logger.info("vk runtime is ready")
    asyncio.run(runtime.start_polling())


if __name__ == "__main__":
    main()
