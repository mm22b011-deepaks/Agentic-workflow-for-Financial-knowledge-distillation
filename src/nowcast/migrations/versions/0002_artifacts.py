"""Fingerprinted stage outputs for bounded inspector execution."""

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'


def upgrade() -> None:
    op.add_column('jobs', sa.Column('request_json', sa.String))
    op.create_table(
        'artifacts',
        sa.Column('job_id', sa.String, sa.ForeignKey('jobs.id'), primary_key=True),
        sa.Column('stage', sa.String, primary_key=True),
        sa.Column('config_fingerprint', sa.String, nullable=False),
        sa.Column('files', sa.String, nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError('Artifact provenance must be preserved')
