"""Read-only SQLite connections for catalog validation and future execution."""

import sqlite3
from pathlib import Path


def connect_readonly(path: Path, timeout: float = 3.0) -> sqlite3.Connection:
    """Open an existing database in read-only mode with query-only enforcement."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,timeout=timeout)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection
