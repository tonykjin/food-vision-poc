"""Helpers for disposable PostgreSQL test databases (see conftest.py)."""

import os
import secrets
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[2]


def admin_url() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        if os.environ.get("REQUIRE_DB_TESTS") == "true":
            pytest.fail("REQUIRE_DB_TESTS=true but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL not set (local disposable Postgres required)")
    return make_url(raw)


def alembic_config(url: URL) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


def create_database() -> URL:
    admin = admin_url()
    name = f"fv_test_{secrets.token_hex(4)}"
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()
    return admin.set(database=name)


def drop_database(url: URL) -> None:
    engine = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    engine.dispose()
