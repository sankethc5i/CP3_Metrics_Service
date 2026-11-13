"""Dataset fingerprinting and locked-split access gates."""

import hashlib
from pathlib import Path
from typing import Any

import yaml

from app.config import AS_OF_DATE


def load_cases(path: Path, database: Path, split: str = "dev", allow_locked: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Refuse locked benchmarking without the explicit opt-in and verify snapshots."""
    if split == "test" and not allow_locked:
        raise ValueError("Locked test requires --allow-locked-test; tune on dev only.")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload["as_of_date"] != AS_OF_DATE.isoformat():
        raise ValueError("AS_OF_DATE differs from the frozen evaluation snapshot.")
    if payload["database_sha256"] != hashlib.sha256(database.read_bytes()).hexdigest():
        raise ValueError("Database differs from the verified ground-truth snapshot.")
    sql_path = path.with_name("ground_truth.sql")
    if payload["sql_sha256"] != hashlib.sha256(sql_path.read_bytes()).hexdigest():
        raise ValueError("Reference SQL differs from the verified snapshot.")
    metadata = {k: v for k, v in payload.items() if k != "cases"}
    metadata["questions_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return metadata, [c for c in payload["cases"] if c["split"] == split]
