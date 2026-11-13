"""Inspect planted SQL without ever executing it or contacting a model."""

from pathlib import Path
from typing import Any

import yaml

from app.sql.validation import validate_query


def benchmark_validator(path: Path) -> dict[str, Any]:
    """Measure actual catches and false positives; retain semantic false negatives."""
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = []
    for kind in ("bad", "benign"):
        for case in cases[kind]:
            rejected = False
            error_type = None
            try:
                validate_query(case["sql"])
            except Exception as error:
                rejected, error_type = True, type(error).__name__
            rows.append({**case, "kind": kind, "rejected": rejected, "error_type": error_type})
    bad = [r for r in rows if r["kind"] == "bad"]
    benign = [r for r in rows if r["kind"] == "benign"]
    return {"bad_count": len(bad), "benign_count": len(benign), "llm_calls": 0,
            "catch_rate": sum(r["rejected"] for r in bad)/len(bad),
            "false_positive_rate": sum(r["rejected"] for r in benign)/len(benign), "cases": rows}
