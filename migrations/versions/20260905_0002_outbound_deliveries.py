"""add outbound_deliveries transactional outbox

Revision ID: 20260905_0002
Revises: 20260905_0001
Create Date: 2026-09-05 15:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260905_0002"
down_revision: str | None = "20260905_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_deliveries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("player_context_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column(
            "action_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "sequence_no >= 0",
            name="ck_outbound_delivery_sequence_no",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'delivered', 'cancelled', 'dead')",
            name="ck_outbound_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_context_id"],
            ["player_contexts.id"],
            name="fk_outbound_delivery_player_context",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name="fk_outbound_delivery_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_outbound_delivery_event_sequence",
        "outbound_deliveries",
        ["player_context_id", "source_event_id", "sequence_no"],
        unique=True,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_outbound_delivery_due",
        "outbound_deliveries",
        ["due_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_outbound_delivery_session_pending",
        "outbound_deliveries",
        ["session_id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_delivery_session_pending",
        table_name="outbound_deliveries",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "ix_outbound_delivery_due",
        table_name="outbound_deliveries",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "uq_outbound_delivery_event_sequence",
        table_name="outbound_deliveries",
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.drop_table("outbound_deliveries")
