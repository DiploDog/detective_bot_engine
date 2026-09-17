from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PlayerContextRow(Base):
    __tablename__ = "player_contexts"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_user_id",
            "external_chat_id",
            name="uq_player_context_identity",
        ),
        CheckConstraint(
            "platform IN ('telegram', 'vk')",
            name="ck_player_context_platform",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_session_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey(
            "game_sessions.id",
            name="fk_player_context_selected_session",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class GameSessionRow(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('in_progress', 'completed', 'superseded')",
            name="ck_game_session_lifecycle_status",
        ),
        CheckConstraint(
            "engine_status IN ('in_progress', 'completed')",
            name="ck_game_session_engine_status",
        ),
        Index(
            "uq_game_session_resumable",
            "player_context_id",
            "game_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'in_progress'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    player_context_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "player_contexts.id",
            name="fk_game_session_player_context",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    game_id: Mapped[str] = mapped_column(String(128), nullable=False)
    game_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_scene: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_status: Mapped[str] = mapped_column(String(32), nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProcessedEventRow(Base):
    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint(
            "player_context_id",
            "external_event_id",
            name="uq_processed_event_identity",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    player_context_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "player_contexts.id",
            name="fk_processed_event_player_context",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ScheduledActionRow(Base):
    __tablename__ = "scheduled_actions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "origin_revision",
            "idempotency_key",
            name="uq_scheduled_action_idempotency",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'cancelled', 'dead')",
            name="ck_scheduled_action_status",
        ),
        Index(
            "ix_scheduled_action_due",
            "due_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "game_sessions.id",
            name="fk_scheduled_action_session",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SessionInteractionRow(Base):
    __tablename__ = "session_interactions"
    __table_args__ = (
        CheckConstraint(
            "input_kind IN ('text', 'choice')",
            name="ck_session_interaction_input_kind",
        ),
        CheckConstraint(
            "input_status IN ('handled', 'invalid', 'fallback', 'stale')",
            name="ck_session_interaction_input_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "game_sessions.id",
            name="fk_session_interaction_session",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    external_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    scene_before: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scene_after: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    outcome_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    input_status: Mapped[str] = mapped_column(String(32), nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class OutboundDeliveryRow(Base):
    __tablename__ = "outbound_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'cancelled', 'dead')",
            name="ck_outbound_delivery_status",
        ),
        CheckConstraint(
            "sequence_no >= 0",
            name="ck_outbound_delivery_sequence_no",
        ),
        Index(
            "uq_outbound_delivery_event_sequence",
            "player_context_id",
            "source_event_id",
            "sequence_no",
            unique=True,
            postgresql_where=text("source_event_id IS NOT NULL"),
        ),
        Index(
            "ix_outbound_delivery_due",
            "due_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_outbound_delivery_session_pending",
            "session_id",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    player_context_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "player_contexts.id",
            name="fk_outbound_delivery_player_context",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey(
            "game_sessions.id",
            name="fk_outbound_delivery_session",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    source_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )


class TelegramMediaCacheRow(Base):
    __tablename__ = "telegram_media_cache"
    __table_args__ = (
        UniqueConstraint(
            "bot_id",
            "asset_sha256",
            "media_kind",
            name="uq_telegram_media_cache_identity",
        ),
        CheckConstraint(
            "media_kind IN ('photo', 'audio', 'document')",
            name="ck_telegram_media_cache_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class VkMediaCacheRow(Base):
    __tablename__ = "vk_media_cache"
    __table_args__ = (
        UniqueConstraint(
            "community_id",
            "asset_sha256",
            "media_kind",
            name="uq_vk_media_cache_identity",
        ),
        CheckConstraint(
            "media_kind IN ('photo', 'audio', 'document', 'voice')",
            name="ck_vk_media_cache_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    attachment: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
