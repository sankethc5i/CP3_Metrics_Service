"""Per-request JSONL traces with recursive credential redaction and step timings."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

_LOCK = threading.Lock()


def redact(value: Any) -> Any:
    """Remove known environment secrets and credential patterns from trace payloads."""
    if isinstance(value,dict):
        return {k:("[REDACTED]" if re.search(r"api.?key|password|secret|authorization|access_token",str(k),re.I)
            else redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [redact(item) for item in value]
    if not isinstance(value,str):
        return value
    for key,secret in os.environ.items():
        if len(secret)>=6 and re.search(r"key|token|password|secret",key,re.I):
            value = value.replace(secret,"[REDACTED]")
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+","[REDACTED]",value)
    value = re.sub(r"(?i)(api[_ -]?key|password|authorization|secret)\s*[:=]\s*[^\s,;]+",r"\1=[REDACTED]",value)
    return value


class Trace:
    """Collect sanitized events and persist a single request record to JSONL."""

    def __init__(self, directory: Path) -> None:
        self.request_id = str(uuid4())
        self.directory = directory
        self.events: list[dict[str,Any]] = []
        self.started = time.perf_counter()

    @contextmanager
    def step(self, name: str) -> Iterator[dict[str,Any]]:
        """Measure a step and record safe error types without exception messages."""
        started = time.perf_counter()
        event: dict[str,Any] = {"step":name,"started_ms":(started-self.started)*1000,
            "tokens":{"input_tokens":0,"output_tokens":0,"total_tokens":0},"status":"ok"}
        try:
            yield event
        except Exception as error:
            event.update(status="error",error_type=type(error).__name__)
            raise
        finally:
            event["latency_ms"] = (time.perf_counter()-started)*1000
            self.events.append(redact(event))

    def save(self, outcome: str) -> float:
        """Append sanitized JSONL under a lock; wall time is telemetry only."""
        elapsed = (time.perf_counter()-self.started)*1000
        record = redact({"request_id":self.request_id,"outcome":outcome,
            "timestamp":datetime.now(timezone.utc).isoformat(),"latency_ms":elapsed,"events":self.events})
        self.directory.mkdir(parents=True,exist_ok=True)
        with _LOCK, (self.directory/"requests.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(record,allow_nan=False)+"\n")
        return elapsed
