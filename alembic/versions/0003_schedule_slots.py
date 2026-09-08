"""schedule_slots: recurring weekly slots a student's lessons are generated from

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schedule_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        # 0 is Monday, 6 is Sunday — same as Python's date.weekday()
        sa.Column("weekday", sa.Integer(), nullable=False),
        # local wall-clock time, converted to UTC when lessons are generated
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.CheckConstraint(
            "weekday >= 0 AND weekday <= 6", name="ck_schedule_slots_weekday"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_schedule_slots_student_id"), "schedule_slots", ["student_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_schedule_slots_student_id"), table_name="schedule_slots")
    op.drop_table("schedule_slots")
