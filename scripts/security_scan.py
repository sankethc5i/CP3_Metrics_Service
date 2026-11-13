"""Scan project files without printing credentials or reading VCS history/vendors."""

from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values
from app.config import ROOT


def main() -> None:
    """Write locations/counts only; distinguish expected dotenv storage from leaks."""
    secrets = {str(v) for k,v in {**dotenv_values(ROOT/".env"),**os.environ}.items()
               if v and len(str(v)) >= 12 and re.search(r"key|token|password|secret",k,re.I)}
    # Include the on-disk key even if an environment override is active.
    secrets.update(str(v) for k,v in dotenv_values(ROOT/".env").items()
                   if v and len(str(v)) >= 12 and re.search(r"key|token|password|secret",k,re.I))
    patterns = [re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
                re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}"),
                re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
                re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{32,}")]
    excluded = {".git",".venv","__pycache__",".pytest_cache",".pytest-tmp"}
    suffixes = {".py",".md",".yaml",".yml",".json",".jsonl",".log",".txt",".toml",".ini",".cfg",".html",".xml",".csv",".example"}
    findings, unreadable, files, traces = [], [], 0, 0
    pii = []
    db_path = ROOT/"data/ecommerce.db"
    with closing(sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        names = [r[0] for r in db.execute("SELECT customer_name FROM customers")]
    def outside_question(value: object) -> list[str]:
        if isinstance(value,dict):
            return [s for k,v in value.items() if k != "question" for s in outside_question(v)]
        if isinstance(value,list):
            return [s for v in value for s in outside_question(v)]
        return [value] if isinstance(value,str) else []
    for directory,dirs,entries in os.walk(ROOT,followlinks=False):
        dirs[:] = [d for d in dirs if d not in excluded and not d.startswith("pytest-cache-files-")
                   and Path(directory)/d != ROOT/"data/models"
                   and not (Path(directory)/d).is_symlink()]
        for entry in entries:
            path = Path(directory)/entry
            if path.is_symlink() or (path.suffix.lower() not in suffixes and not entry.startswith(".env") and entry != ".gitignore"):
                continue
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8",errors="replace")
            except OSError:
                unreadable.append(path.relative_to(ROOT).as_posix())
                continue
            files += 1
            relative = path.relative_to(ROOT).as_posix()
            for number,line in enumerate(text.splitlines(),1):
                known = any(secret in line for secret in secrets)
                candidates = [m.group() for pattern in patterns for m in pattern.finditer(line)]
                candidates = [s for s in candidates if not s.startswith(("sk-test-","sk-fake-","sk-secret-"))]
                if known or candidates:
                    findings.append({"file":relative,"line":number,"kind":"configured_secret" if known else "unverified_credential_pattern",
                                     "expected_dotenv_storage":relative==".env"})
            if path.suffix == ".jsonl":
                traces += 1
                for number,line in enumerate(text.splitlines(),1):
                    try:
                        strings = outside_question(json.loads(line))
                    except ValueError:
                        pii.append({"file":relative,"line":number,"kind":"unparseable_jsonl"})
                        continue
                    if any(name in s for name in names for s in strings):
                        pii.append({"file":relative,"line":number,"kind":"warehouse_customer_name_outside_question"})
    report = {"scope":"working tree only; no VCS history, vendor/model binaries or pytest scratch directories",
              "files_scanned":files,"jsonl_files_scanned":traces,"unreadable":unreadable,
              "findings":findings,"pii_checks":pii,
              "limitations":"Known credential values and selected credential patterns; customer-name checks are not a complete PII detector."}
    target = ROOT/"eval/reports/security/secret-scan.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"files_scanned":files,"jsonl_files_scanned":traces,
                      "finding_counts":dict(Counter(f["kind"] for f in findings)),
                      "locations":findings,"pii_check_count":len(pii),"unreadable_count":len(unreadable)},indent=2))


if __name__ == "__main__":
    main()
