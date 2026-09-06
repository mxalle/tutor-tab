"""parent_invites: one-shot links binding a parent chat to a student

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parent_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_parent_invites_student_id"), "parent_invites", ["student_id"]
    )
    op.create_index(
        op.f("ix_parent_invites_token"), "parent_invites", ["token"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_parent_invites_token"), table_name="parent_invites")
    op.drop_index(op.f("ix_parent_invites_student_id"), table_name="parent_invites")
    op.drop_table("parent_invites")
