"""Offline CLI integration and paid/locked gates use stub models and real exports."""

import csv
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.config import DATABASE_PATH, ROOT, Settings
from app.evaluation.dataset import load_cases
from tests.test_service import FakeModel, service


def test_cli_writes_comparable_reports_without_paid_calls(warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The full offline runner exports numeric scores, CSV, charts and step traces."""
    import app.evaluation.runner as runner
    from app.evaluation.validator import benchmark_validator
    metadata, cases = load_cases(ROOT/"eval/questions.yaml", DATABASE_PATH)
    probes = benchmark_validator(ROOT/"eval/validator_queries.yaml")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "load_cases", lambda *a: (metadata, cases))
    monkeypatch.setattr(runner, "benchmark_validator", lambda _: probes)
    settings = Settings(database=warehouse, llm_cache_dir=tmp_path/"llm", cache_dir=tmp_path/"vectors")
    monkeypatch.setattr(runner, "load_settings", lambda: settings)
    def factory(config: Settings):
        app = service(warehouse, tmp_path, FakeModel(), config.rag_mode)
        app.settings = config
        return app
    monkeypatch.setattr(runner, "create_service", factory)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Offline evaluation requested paid-call confirmation"))
    runner.main(["--mode", "lookup", "--limit", "2", "--output", "export_check"])
    target = tmp_path/"eval/reports/dev_export_check"
    report = json.loads((target/"results.json").read_text())
    assert report["paid_calls"] == 0 and Decimal(report["spent_usd"]) == 0
    assert report["modes"]["lookup"]["summary"]["answer_exactness"] == 1
    assert len(list(csv.DictReader((target/"questions.csv").open()))) == 2
    assert len((target/"traces.jsonl").read_text().splitlines()) == 2
    assert (target/"comparison.png").read_bytes().startswith(b"\x89PNG")
    assert "<svg" in (target/"comparison.svg").read_text()
    assert "oracle" in (target/"report.md").read_text().lower()
    with pytest.raises(SystemExit):
        runner.main(["--mode", "lookup", "--output", "export_check"])
    with pytest.raises(SystemExit):
        runner.main(["--mode", "lookup", "--case-ids", "not-in-dev"])


@pytest.mark.parametrize("flags", [
    ["--split", "test"], ["--live", "--retrieval-only"], ["--live", "--validator-only"],
    ["--limit", "0"], ["--max-cost", "NaN"], ["--max-cost", "-1"],
])
def test_cli_invalid_or_locked_runs_never_load_models(flags: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsafe/contradictory CLI requests terminate before config or model creation."""
    import app.evaluation.runner as runner
    monkeypatch.setattr(runner, "load_settings", lambda: pytest.fail("Invalid run loaded a model/config"))
    with pytest.raises(SystemExit):
        runner.main(flags)
