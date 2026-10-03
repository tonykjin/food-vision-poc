"""Alembic environment. URL precedence: `sqlalchemy.url` set programmatically (tests),
then the MIGRATION_DATABASE_URL environment variable. Never read from app env files."""

import os

from alembic import context
from sqlalchemy import create_engine

from foodvision.data.models import SCHEMAS, metadata

config = context.config


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (owner/migration role) to run migrations.")
    return url


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=metadata,
        include_schemas=True,
        include_name=include_name,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
