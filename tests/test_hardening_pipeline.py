"""Safe failures, date boundaries, paraphrases and structured-answer integration."""

import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import httpx
from openai import APITimeoutError, RateLimitError
import pytest

from app.answers.calculator import calculate
from app.answers.render import render
from app.config import DATABASE_PATH, ROOT
from app.evaluation.dataset import load_cases
from app.evaluation.oracle import OracleModel
from app.llm.schemas import SelectMetric, TimeRange, ToolCall
from app.semantic.dates import resolve_dates
from tests.test_corrective import CorrectiveModel, corrective_app
from tests.test_pipeline_safety import arguments
from tests.test_service import FakeModel, service


@pytest.mark.parametrize("period,expected", [
    ("last_month", ("2026-10-01", "2026-11-01")),
    ("last_quarter", ("2026-07-01", "2026-10-01")),
    ("this_year", ("2026-01-01", "2026-11-01")),
    ("this_month", ("2026-11-01", "2026-11-01")),
    ("this_quarter", ("2026-10-01", "2026-11-01")),
    ("last_year", ("2025-01-01", "2026-01-01")),
    ("last_30_days", ("2026-10-02", "2026-11-01")),
])
def test_frozen_relative_dates(period: str, expected: tuple[str, str]) -> None:
    """All relative periods resolve against the frozen snapshot, never wall time."""
    assert resolve_dates(TimeRange(start=None, end=None, relative=period)) == expected


@pytest.mark.parametrize("anchor,period,expected", [
    ("2026-01-01", "last_month", ("2025-12-01", "2026-01-01")),
    ("2026-01-01", "last_quarter", ("2025-10-01", "2026-01-01")),
    ("2024-03-01", "last_month", ("2024-02-01", "2024-03-01")),
])
def test_calendar_rollovers(anchor: str, period: str, expected: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarter/year rollover and leap month retain correct half-open bounds."""
    from datetime import date
    monkeypatch.setattr("app.semantic.dates.AS_OF_DATE", date.fromisoformat(anchor))
    assert resolve_dates(TimeRange(start=None, end=None, relative=period)) == expected


@pytest.mark.parametrize("bounds", [("2026-11-01", "2026-11-01"), ("2026-02-30", "2026-03-01"), ("2026-03-01", "2026-02-01")])
def test_invalid_absolute_date_ranges(bounds: tuple[str, str]) -> None:
    """Malformed, reversed and equal explicit ranges are never guessed."""
    with pytest.raises(ValueError):
        resolve_dates(TimeRange(start=bounds[0], end=bounds[1], relative=None))


@pytest.mark.parametrize("case_id", ["synonym-01", "synonym-02", "synonym-03", "synonym-05", "synonym-06"])
def test_all_five_corrective_paraphrase_regressions(case_id: str, warehouse: Path, tmp_path: Path) -> None:
    """Validated tool resolution replaces the brittle exact-name intent gate."""
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    case = next(c for c in cases if c["id"] == case_id)
    app = corrective_app(warehouse, tmp_path, CorrectiveModel(["sufficient"]))
    app.settings = app.settings.model_copy(update={"rerank_enabled": False, "evidence_k": 10})
    # Ensure all needed approved definitions are present, independently of stub embeddings.
    from app.retrieval.chunks import Hit
    target = next(c for c in app.retrieval.lookup.chunks if c.metadata.get("metric_id") == case["expected_metric_id"])
    app.retrieval.candidates = lambda *a: [Hit(target, 1)]
    app.model = OracleModel(case)
    response = app.ask(case["question"])
    assert response.outcome == "answer", response.text
    assert response.rows == case["verified_answer"]
    assert "intent_resolution" in response.crag_path
    assert response.model_calls <= app.settings.max_llm_calls
    call = next(e for e in response.trace if e["step"] == "function_call")
    assert call["source"] == "validated_intent_reuse"


@pytest.mark.parametrize("call,outcome", [
    (ToolCall("execute_sql", {"sql": "DROP TABLE orders"}), "refuse"),
    (ToolCall("select_metric", arguments("unknown_metric").model_dump()), "refuse"),
    (ToolCall("select_metric", arguments("orders", dimensions=["category"]).model_dump()), "refuse"),
    (ToolCall("select_metric", {"metric_id": "net_revenue"}), "refuse"),
    (ToolCall("request_clarification", {"options": ["gross_revenue", "net_revenue"]}), "clarify"),
    (ToolCall("refuse", {"reason": "Undefined metric"}), "refuse"),
])
def test_paraphrase_resolution_cannot_bypass_governance(call: ToolCall, outcome: str, warehouse: Path, tmp_path: Path) -> None:
    """Semantic resolution still exposes only three tools and enforces all argument checks."""
    model = CorrectiveModel(["sufficient"])
    model.call = call
    response = corrective_app(warehouse, tmp_path, model).ask("Tell me about the checkout receipts")
    assert response.outcome == outcome and response.sql is None
    assert "db_execution" not in [e["step"] for e in response.trace]


@pytest.mark.parametrize("error,expected", [
    (APITimeoutError(request=httpx.Request("POST", "https://example.invalid")), "timed out"),
    (RateLimitError("private credential detail", response=httpx.Response(429, request=httpx.Request("POST", "https://example.invalid")), body=None), "rate limit"),
])
def test_provider_failures_have_safe_messages(error: Exception, expected: str, warehouse: Path, tmp_path: Path) -> None:
    """Model timeout/rate-limit details never leak to UI or trace."""
    app = service(warehouse, tmp_path, FakeModel())
    with patch.object(app.model, "select", side_effect=error):
        response = app.ask("Net revenue")
    assert response.outcome == "refuse" and expected in response.text
    assert response.value is None and response.sql is None
    assert "private credential detail" not in json.dumps(response.model_dump(mode="json"))


def test_db_failure_is_safe_and_traced(warehouse: Path, tmp_path: Path) -> None:
    """A DB error yields refusal, retains diagnostic stage, and hides sensitive paths."""
    app = service(warehouse, tmp_path, FakeModel())
    with patch("app.service.execute_query", side_effect=sqlite3.OperationalError("private-path sk-secret-value")):
        response = app.ask("Net revenue")
    assert response.outcome == "refuse" and "database" in response.text
    assert response.value is None and response.rows == []
    event = next(e for e in response.trace if e["step"] == "db_execution")
    assert event["status"] == "error" and event["error_type"] == "OperationalError"
    assert "private-path" not in json.dumps(response.model_dump(mode="json"))


def test_calculation_references_are_deterministic_and_unknowns_rejected() -> None:
    """Only calculator-produced percentages and shares can fill calc references."""
    rows = [{"category": "A", "net_revenue": 30}, {"category": "B", "net_revenue": 70}]
    values = calculate(rows, "net_revenue", "USD", ("category",))
    assert render("Share {{calc.row0_visible_share_percentage}}%", {}, values) == "Share 30%"
    for template in ("{{calc.invented}}", "{{result.fake}}", "{{result.net_revenue}", "A gain of 99 percent"):
        with pytest.raises(ValueError):
            render(template, {"net_revenue": 100}, values)


def test_invented_template_rejected_in_full_pipeline(warehouse: Path, tmp_path: Path) -> None:
    """An invented reference is never presented; the renderer uses safe query-sourced fallback."""
    response = service(warehouse, tmp_path, FakeModel(template="{{calc.fake_profit}} dollars")).ask("Net revenue")
    assert response.outcome == "answer" and response.template_source == "deterministic"
    assert "fake_profit" not in response.text


def test_trace_all_success_steps_and_secret_redaction(warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer path has every stage, elapsed time and tokens, without secret values."""
    secret = "sk-test-secret-never-log-this"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    response = service(warehouse, tmp_path, FakeModel()).ask("Net revenue "+secret)
    expected = ["question_received", "retrieval", "function_call", "argument_validation", "catalog_metric_check",
                "allow_list_validation", "sql_compile", "sql_validation", "db_execution", "answer_generation"]
    assert [e["step"] for e in response.trace] == expected
    assert all(e["latency_ms"] >= 0 and "tokens" in e for e in response.trace)
    assert secret not in json.dumps(response.model_dump(mode="json"))
    assert secret not in (tmp_path/"traces"/"requests.jsonl").read_text()


def test_live_estimate_over_hard_cap_is_rejected_before_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run whose conservative estimate exceeds the user's cap never asks or spends."""
    from decimal import Decimal
    from types import SimpleNamespace
    import app.evaluation.runner as runner
    from app.config import ModelPrice, Settings
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Over-budget run requested approval"))
    settings = Settings(model="stub", model_prices={"stub": ModelPrice(input_per_million="0.10", output_per_million="0.50", cached_input_per_million="0.01")})
    with pytest.raises(ValueError, match="Estimated live cost exceeds"):
        runner.confirm_live(SimpleNamespace(limit=10, max_cost=Decimal("0.10")), settings, 10, 1)


def test_provider_cached_input_pricing() -> None:
    """Provider-cached inputs use the configured cached tier; disk hits remain zero."""
    from decimal import Decimal
    from app.config import ModelPrice
    from app.llm.cache import Ledger
    ledger = Ledger({"stub": ModelPrice(input_per_million="0.10", output_per_million="0.50", cached_input_per_million="0.01")}, Decimal("0.15"))
    assert ledger.cost("stub", {"input_tokens": 1000, "provider_cached_input_tokens": 800, "output_tokens": 100}) == Decimal("0.000078")


def test_operand_mentions_do_not_override_requested_intent(warehouse: Path) -> None:
    """Adjustment operands trigger semantic resolution while explicit competing metrics remain ambiguous."""
    from app.retrieval.evidence import matching_metrics
    from app.semantic.loader import load_catalog
    catalog = load_catalog(database=warehouse)
    assert matching_metrics("Money made after reductions and refunds", catalog) == []
    assert matching_metrics("Show refunds", catalog) == ["refunds"]
    assert set(matching_metrics("Compare gross revenue and net revenue", catalog)) == {"gross_revenue", "net_revenue"}


def test_correction_retains_validated_definition_even_if_reranker_drops_it(warehouse: Path, tmp_path: Path) -> None:
    """An exact catalog correction retains evidence, but still requires a sufficient grade."""
    from app.retrieval.chunks import Hit
    _, cases = load_cases(ROOT/"eval/questions.yaml", DATABASE_PATH)
    case = next(c for c in cases if c["id"] == "synonym-03")
    app = corrective_app(warehouse, tmp_path, CorrectiveModel(["sufficient"]))
    app.model = OracleModel(case)
    definitions = [Hit(c, 1) for c in app.retrieval.lookup.chunks if c.kind == "metric"]
    app.retrieval.candidates = lambda *a: definitions
    # A deliberately unhelpful reranker always omits the valid selected definition.
    app.reranker.rerank = lambda q, hs, *a: [h for h in hs if h.chunk.id != "metric:order_lines"][:10]
    response = app.ask(case["question"])
    assert response.outcome == "answer" and response.rows == case["verified_answer"]
    assert "correction" in response.crag_path
    assert response.evidence_grades[-1]["metric_found"] is True
    assert response.evidence_grades[-1]["next_action"] == "proceed"
