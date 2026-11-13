"""Execute only authored reference SQL, independently of the production compiler."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.config import ROOT

FILTERS = ("category", "brand", "order_region", "customer_region", "device", "traffic_source",
           "age_group", "status", "month", "quarter")


def reference_sql(path: Path = ROOT/"eval"/"ground_truth.sql") -> dict[str, str]:
    """Read named handwritten SQL blocks; never derive SQL from the catalog."""
    pieces = re.split(r"^-- name: (\w+)\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    return {pieces[i]: pieces[i+1].strip() for i in range(1, len(pieces), 2)}


def verify_answer(case: dict[str, Any], database: Path) -> list[dict[str, Any]] | None:
    """Compute reference rows from raw tables for answer and empty-result cases."""
    if case["expected_outcome"] not in {"answer", "empty_result"}:
        return None
    blocks = reference_sql()
    spec = case["ground_truth"]
    params = {key: None for key in FILTERS}
    params.update(spec["parameters"])
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.row_factory = sqlite3.Row
        rows = connection.execute(blocks["common"]+"\n"+blocks[spec["query"]], params).fetchall()
    fields = [*case["dimensions"], *([] if case["grain"] == "total" else [case["grain"]]), case["expected_metric_id"]]
    return [{key: row[key] for key in fields} for row in rows]
