"""extend audit_log with structured fields

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("turn_number", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("audit_log", sa.Column("tool_name", sa.String(128), nullable=True, server_default=""))
    op.add_column("audit_log", sa.Column("tool_args", sa.Text(), nullable=True, server_default=""))
    op.add_column("audit_log", sa.Column("tool_result_summary", sa.Text(), nullable=True, server_default=""))
    op.add_column("audit_log", sa.Column("model_response_summary", sa.Text(), nullable=True, server_default=""))


def downgrade() -> None:
    op.drop_column("audit_log", "model_response_summary")
    op.drop_column("audit_log", "tool_result_summary")
    op.drop_column("audit_log", "tool_args")
    op.drop_column("audit_log", "tool_name")
    op.drop_column("audit_log", "turn_number")
