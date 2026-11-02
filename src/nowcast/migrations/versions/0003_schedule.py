"""Schedule planning metadata and durable request receipts share the job database."""

import sqlalchemy as sa
from alembic import op

revision = '0003_schedule'
down_revision = '0002'


def upgrade() -> None:
    op.create_table(
        'schedule_state',
        sa.Column('key', sa.String, primary_key=True),
        sa.Column('value', sa.String, nullable=False),
    )
    op.create_table(
        'schedule_tasks',
        sa.Column('task_key', sa.String, primary_key=True),
        sa.Column('command', sa.String, nullable=False),
        sa.Column('dependencies', sa.String, nullable=False),
        sa.Column('earliest_day', sa.String, nullable=False),
        sa.Column('quota_cost', sa.Integer, nullable=False),
        sa.Column('status', sa.String, nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('last_error', sa.String),
        sa.Column('next_eligible', sa.Float, nullable=False),
        sa.Column('last_job', sa.String, sa.ForeignKey('jobs.id')),
        sa.Column('human', sa.Boolean, nullable=False),
        sa.Column('parameters', sa.String, nullable=False),
    )
    op.create_table(
        'request_receipts',
        sa.Column('request_key', sa.String, primary_key=True),
        sa.Column('status', sa.String, nullable=False),
        sa.Column('pid', sa.Integer, nullable=False),
        sa.Column('identity', sa.String, nullable=False),
        sa.Column('result', sa.String),
        sa.Column('created_at', sa.Float, nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError('Schedule history and request receipts must be preserved')
