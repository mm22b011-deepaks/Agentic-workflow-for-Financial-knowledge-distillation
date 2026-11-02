"""Initial workstation job, event and quota reservation schema."""

import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('submission_id', sa.String, nullable=False, unique=True),
        sa.Column('workflow_id', sa.String, nullable=False),
        sa.Column('status', sa.String, nullable=False),
        sa.Column('stage', sa.String),
        sa.Column('completed', sa.Integer, nullable=False),
        sa.Column('total', sa.Integer, nullable=False),
        sa.Column('cancel_requested', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.String, nullable=False),
        sa.Column('config_path', sa.String, nullable=False),
        sa.Column('fingerprint', sa.String, nullable=False),
        sa.Column('stages', sa.String, nullable=False),
        sa.Column('pid', sa.Integer),
        sa.Column('identity', sa.String),
    )
    op.create_table(
        'events',
        sa.Column('sequence', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.String, sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('stage', sa.String),
        sa.Column('kind', sa.String, nullable=False),
        sa.Column('created_at', sa.String, nullable=False),
    )
    op.create_table(
        'reservations',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('scope', sa.String, nullable=False),
        sa.Column('timestamp', sa.Float, nullable=False),
        sa.Column('utc_day', sa.String, nullable=False),
    )
    op.create_index('ix_quota_scope_time', 'reservations', ['scope', 'timestamp'])
    op.create_table(
        'cooldowns',
        sa.Column('scope', sa.String, primary_key=True),
        sa.Column('resume_at', sa.Float, nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError('Job history and quota reservations must be preserved')
