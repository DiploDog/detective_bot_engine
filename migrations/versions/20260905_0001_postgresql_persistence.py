"""create application persistence tables

Revision ID: 20260905_0001
Revises:
Create Date: 2026-09-05 14:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260905_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_contexts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("external_chat_id", sa.String(length=255), nullable=False),
        sa.Column("selected_session_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "platform IN ('telegram', 'vk')",
            name="ck_player_context_platform",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "external_user_id",
            "external_chat_id",
            name="uq_player_context_identity",
        ),
    )
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("player_context_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.String(length=128), nullable=False),
        sa.Column("game_version", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("current_scene", sa.String(length=128), nullable=False),
        sa.Column("engine_status", sa.String(length=32), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "engine_status IN ('in_progress', 'completed')",
            name="ck_game_session_engine_status",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('in_progress', 'completed', 'superseded')",
            name="ck_game_session_lifecycle_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_context_id"],
            ["player_contexts.id"],
            name="fk_game_session_player_context",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_game_session_resumable",
        "game_sessions",
        ["player_context_id", "game_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'in_progress'"),
    )
    op.create_foreign_key(
        "fk_player_context_selected_session",
        "player_contexts",
        "game_sessions",
        ["selected_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "processed_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("player_context_id", sa.BigInteger(), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_context_id"],
            ["player_contexts.id"],
            name="fk_processed_event_player_context",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_context_id",
            "external_event_id",
            name="uq_processed_event_identity",
        ),
    )
    op.create_table(
        "scheduled_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("template_id", sa.String(length=128), nullable=False),
        sa.Column("origin_revision", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'cancelled', 'dead')",
            name="ck_scheduled_action_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name="fk_scheduled_action_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "origin_revision",
            "idempotency_key",
            name="uq_scheduled_action_idempotency",
        ),
    )
    op.create_index(
        "ix_scheduled_action_due",
        "scheduled_actions",
        ["due_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "session_interactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("scene_before", sa.String(length=128), nullable=True),
        sa.Column("scene_after", sa.String(length=128), nullable=True),
        sa.Column("interaction_id", sa.String(length=128), nullable=True),
        sa.Column("outcome_id", sa.String(length=128), nullable=True),
        sa.Column("input_kind", sa.String(length=32), nullable=False),
        sa.Column("input_status", sa.String(length=32), nullable=False),
        sa.Column("invalid_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_kind IN ('text', 'choice')",
            name="ck_session_interaction_input_kind",
        ),
        sa.CheckConstraint(
            "input_status IN ('handled', 'invalid', 'fallback', 'stale')",
            name="ck_session_interaction_input_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name="fk_session_interaction_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("session_interactions")
    op.drop_index(
        "ix_scheduled_action_due",
        table_name="scheduled_actions",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("scheduled_actions")
    op.drop_table("processed_events")
    op.drop_constraint(
        "fk_player_context_selected_session",
        "player_contexts",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_game_session_resumable",
        table_name="game_sessions",
        postgresql_where=sa.text("lifecycle_status = 'in_progress'"),
    )
    op.drop_table("game_sessions")
    op.drop_table("player_contexts")
