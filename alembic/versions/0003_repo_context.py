"""add repo context columns to sessions

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("repo_url", sa.String(2048), nullable=True))
    op.add_column("sessions", sa.Column("repo_type", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("primary_language", sa.String(64), nullable=True))
    op.add_column("sessions", sa.Column("repo_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("sessions", sa.Column("health_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "health_score")
    op.drop_column("sessions", "repo_context")
    op.drop_column("sessions", "primary_language")
    op.drop_column("sessions", "repo_type")
    op.drop_column("sessions", "repo_url")
