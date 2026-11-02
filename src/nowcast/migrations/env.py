"""Application-owned connection; no credentials or filesystem URL in migration config."""

from alembic import context

connection = context.config.attributes['connection']
context.configure(connection=connection)
with context.begin_transaction():
    context.run_migrations()
