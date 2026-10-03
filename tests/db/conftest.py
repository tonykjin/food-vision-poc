"""Disposable PostgreSQL databases for migration and access tests.

TEST_DATABASE_URL must point at a local/CI admin connection (dummy credentials only).
Each session creates a brand-new database, migrates it from empty with Alembic and drops it.
Without the variable the tests skip, unless REQUIRE_DB_TESTS=true (CI), where they fail.
"""

import secrets
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from tests.db.helpers import admin_url, alembic_config, create_database, drop_database


@pytest.fixture
def empty_db() -> Iterator[URL]:
    url = create_database()
    yield url
    drop_database(url)


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[URL]:
    url = create_database()
    command.upgrade(alembic_config(url), "head")
    yield url
    drop_database(url)


@pytest.fixture
def owner(migrated_db):
    engine = create_engine(migrated_db)
    yield engine
    engine.dispose()


@pytest.fixture
def login_as(migrated_db):
    """Create a real LOGIN user in a group role and return an engine connected as it."""
    created: list[tuple[str, object]] = []

    def make(group: str):
        name = f"fv_login_{secrets.token_hex(4)}"
        password = secrets.token_urlsafe(16)  # random per test; never printed or stored
        admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f"CREATE ROLE {name} LOGIN PASSWORD '{password}' IN ROLE {group}"))
        admin.dispose()
        engine = create_engine(migrated_db.set(username=name, password=password))
        created.append((name, engine))
        return engine

    yield make
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    for name, engine in created:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP ROLE IF EXISTS {name}"))
    admin.dispose()
