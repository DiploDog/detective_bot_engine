from tests.fakes.application import (
    InMemoryInteractionLogRepository,
    InMemoryOutboundDeliveryRepository,
    InMemoryProcessedEventRepository,
    InMemoryScheduledActionRepository,
    InMemorySessionRepository,
    InMemoryUnitOfWork,
    InMemoryUnitOfWorkFactory,
)
from tests.fakes.telegram import (
    InMemoryTelegramMediaCache,
    MappingMediaResolver,
    RecordingTelegramSender,
)
from tests.fakes.vk import InMemoryVkMediaCache, RecordingVkSender

__all__ = [
    "InMemoryInteractionLogRepository",
    "InMemoryOutboundDeliveryRepository",
    "InMemoryProcessedEventRepository",
    "InMemoryScheduledActionRepository",
    "InMemorySessionRepository",
    "InMemoryUnitOfWork",
    "InMemoryUnitOfWorkFactory",
    "InMemoryTelegramMediaCache",
    "MappingMediaResolver",
    "RecordingTelegramSender",
    "InMemoryVkMediaCache",
    "RecordingVkSender",
]
