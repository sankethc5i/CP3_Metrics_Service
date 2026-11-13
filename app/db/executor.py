"""Bounded read-only execution that always revalidates SQL before touching SQLite."""

from contextlib import closing
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.db.connection import connect_readonly
from app.sql.compiler import CompiledQuery
from app.sql.validation import validate_query


def execute_query(query: CompiledQuery, database: Path, timeout: float = 3.0) -> list[dict[str,Any]]:
    """Validate first, then enforce mode=ro, query_only, deadline and maximum rows."""
    if not 1 <= query.max_rows <= 500:
        raise ValueError("Execution row cap must be between one and five hundred")
    validate_query(query.sql,query.max_rows)
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    deadline = time.monotonic()+timeout
    with closing(connect_readonly(database,timeout=timeout)) as connection:
        connection.set_progress_handler(lambda: int(time.monotonic()>deadline),100)
        rows = connection.execute(query.sql,query.parameters).fetchmany(query.max_rows+1)
        if len(rows)>query.max_rows:
            raise ValueError("Result exceeded maximum rows")
        return [dict(row) for row in rows]
