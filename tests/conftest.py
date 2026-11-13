"""Synthetic test fixtures isolated from the delivered warehouse."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from app.db.connection import connect_readonly
from app.db.seed import create_warehouse


def pytest_addoption(parser: pytest.Parser) -> None:
    """Require explicit opt-in before any paid smoke can run."""
    parser.addoption("--run-live-smoke", action="store_true", default=False)


def pytest_configure(config: pytest.Config) -> None:
    """Register the paid-network marker without enabling it."""
    config.addinivalue_line("markers", "live: explicitly approved paid dev smoke, skipped by default")


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build one independent fixed-seed warehouse for read-only tests."""
    path = tmp_path_factory.mktemp("warehouse") / "ecommerce.db"
    create_warehouse(path)
    return path


@pytest.fixture
def db(warehouse: Path) -> Iterator[sqlite3.Connection]:
    """Yield a read-only test connection and close it after use."""
    with closing(connect_readonly(warehouse)) as connection:
        yield connection
