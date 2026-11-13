"""Evaluation contracts use stubs and independent SQL; no network or locked runs."""

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from app.answers.render import AnswerTemplate
from app.config import DATABASE_PATH, ROOT, ModelPrice, Settings
from app.evaluation.dataset import load_cases
from app.evaluation.ground_truth import verify_answer
from app.evaluation.metrics import aggregate, exact_rows, percentile, retrieval_scores
from app.evaluation.oracle import OracleModel
from app.evaluation.runner import confirm_live, relevant_chunks
from app.evaluation.validator import benchmark_validator
from app.llm.cache import CachedLanguageModel, Ledger, SpendLimit
from app.llm.schemas import ToolCall
from app.retrieval.evidence import Judgement, Rewrite


class StubModel:
    """Count transport-boundary calls without importing an API client."""

    def __init__(self) -> None:
        self.calls = 0

    def _value(self, value: Any) -> Any:
        self.calls += 1
        return value

    def select(self, *args: Any) -> ToolCall:
        """Return an authored tool call."""
        return self._value(ToolCall("refuse", {"reason": "Unsupported"}, {"input_tokens": 10, "output_tokens": 2}))

    def answer(self, *args: Any) -> Any:
        """Return a deterministic template."""
        return self._value((AnswerTemplate(template="{{result.row_count}} groups"), {"input_tokens": 10, "output_tokens": 2}))

    def judge(self, *args: Any) -> Any:
        """Return structured evidence judgement."""
        return self._value((Judgement(verdict="sufficient", confidence=1, missing_aspects=[], conflicts=[]), {"input_tokens": 10, "output_tokens": 2}))

    def rewrite(self, *args: Any) -> Any:
        """Return an unchanged query."""
        return self._value((Rewrite(query="question"), {"input_tokens": 10, "output_tokens": 2}))


def test_taxonomy_and_split() -> None:
    """Inspect labels only; never run the locked system benchmark."""
    data = yaml.safe_load((ROOT/"eval"/"questions.yaml").read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) == len({c["id"] for c in cases}) == 77
    assert Counter(c["split"] for c in cases) == {"dev": 55, "test": 22}
    assert set(Counter(c["category"] for c in cases).values()) == {7}
    assert {c["expected_outcome"] for c in cases} == {"answer", "clarify", "refuse", "empty_result"}
    assert all({"expected_metric_id", "dimensions", "filters", "verified_answer"} <= c.keys() for c in cases)


def test_dev_reference_answers_remain_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every dev numeric label is reproducible without the service compiler."""
    import app.sql.compiler
    monkeypatch.setattr(app.sql.compiler, "compile_request", lambda *a, **kw: pytest.fail("Reference SQL used compiler"))
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    for case in cases:
        assert verify_answer(case, DATABASE_PATH) == case["verified_answer"]


def test_locked_gate_precedes_file_access(tmp_path: Path) -> None:
    """Locked tests require opt-in even when the requested path is nonexistent."""
    with pytest.raises(ValueError, match="allow-locked-test"):
        load_cases(tmp_path/"missing.yaml", tmp_path/"missing.db", "test")


def test_snapshot_mismatch(tmp_path: Path) -> None:
    """Fail rather than compare answers from a different database snapshot."""
    fake = tmp_path/"other.db"
    fake.write_bytes(b"different")
    with pytest.raises(ValueError, match="Database differs"):
        load_cases(ROOT/"eval"/"questions.yaml", fake)


@pytest.mark.parametrize("method", ["select", "answer", "judge", "rewrite"])
def test_every_model_route_is_persistently_cached(tmp_path: Path, method: str) -> None:
    """Fresh instances replay all model routes with zero newly billed tokens."""
    settings = Settings(llm_cache_dir=tmp_path)
    model = StubModel()
    first = getattr(CachedLanguageModel(settings, delegate=model), method)("same prompt")
    assert model.calls == 1
    cached = CachedLanguageModel(settings)
    second = getattr(cached, method)("same prompt")
    usage = second.tokens if method == "select" else second[1]
    assert usage["input_tokens"] == usage["output_tokens"] == 0
    assert usage["cache_hit"] == 1 and usage["cached_input_tokens"] == 10
    assert cached.sources == ["cached"]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_cache_identity_includes_model_prompt_and_evidence(tmp_path: Path) -> None:
    """Different models and candidate contexts never reuse cached selection."""
    settings = Settings(llm_cache_dir=tmp_path)
    model = StubModel()
    CachedLanguageModel(settings, delegate=model).select("question", ["net"])
    CachedLanguageModel(settings, delegate=model).select("question", ["gross"])
    CachedLanguageModel(settings.model_copy(update={"model": "other"}), delegate=model).select("question", ["net"])
    assert model.calls == 3


def test_oracle_outputs_never_pollute_paid_cache(tmp_path: Path) -> None:
    """Offline replay cannot masquerade as a cached model response."""
    cache = CachedLanguageModel(Settings(llm_cache_dir=tmp_path), oracle=StubModel())
    cache.select("question")
    assert cache.sources == ["oracle"] and not list(tmp_path.glob("*.json"))


def test_ledger_prices_and_hard_stop(tmp_path: Path) -> None:
    """Budget checks happen before transport; costs use configured rates only."""
    settings = Settings(model_prices={"stub": ModelPrice(input_per_million=Decimal("2"), output_per_million=Decimal("8"))},
                        model="stub", llm_cache_dir=tmp_path)
    ledger = Ledger(settings.model_prices, Decimal("0.001"))
    assert ledger.cost("stub", {"input_tokens": 100, "output_tokens": 50}) == Decimal("0.0006")
    model = StubModel()
    with pytest.raises(SpendLimit):
        CachedLanguageModel(settings, delegate=model, ledger=ledger).select("question")
    assert model.calls == 0 and ledger.exhausted


def test_ledger_reconciles_and_cache_spends_nothing(tmp_path: Path) -> None:
    """Repeated cached calls require no reservation, including when budget is exhausted."""
    settings = Settings(model_prices={"stub": ModelPrice(input_per_million=2, output_per_million=8)}, model="stub", llm_cache_dir=tmp_path)
    ledger = Ledger(settings.model_prices, Decimal("1"))
    cache = CachedLanguageModel(settings, delegate=StubModel(), ledger=ledger)
    cache.select("question")
    assert ledger.spent == Decimal("0.000036") and ledger.calls == 1
    ledger.exhausted = True
    cache.select("question")
    assert ledger.spent == Decimal("0.000036") and ledger.calls == 1


def test_live_requires_price_budget_small_first_run_and_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise approval guards using stubs, without making even one paid call."""
    import app.evaluation.runner as runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    args = SimpleNamespace(limit=10, max_cost=Decimal("3"))
    with pytest.raises(ValueError, match="MODEL_PRICES_JSON"):
        confirm_live(args, Settings(), 10, 1)
    settings = Settings(model="stub", model_prices={"stub": ModelPrice(input_per_million=2, output_per_million=8)})
    args.limit = 20
    with pytest.raises(ValueError, match="first live run"):
        confirm_live(args, settings, 20, 1)
    args.limit = 10
    monkeypatch.setattr("builtins.input", lambda _: "no")
    with pytest.raises(ValueError, match="cancelled"):
        confirm_live(args, settings, 10, 1)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    ledger = confirm_live(args, settings, 10, 1)
    assert ledger.calls == 0 and ledger.spent == 0


def test_numeric_exactness_grouping_and_tolerance() -> None:
    """Missing groups, swapped dimensions and wrong values cannot pass exactness."""
    assert exact_rows([{"category": "A", "net": 1.0000001}], [{"category": "A", "net": 1}])
    assert not exact_rows([{"category": "B", "net": 1}], [{"category": "A", "net": 1}])
    assert not exact_rows([], [{"net": 0}])
    assert not exact_rows([{"net": float("nan")}], [{"net": 1}])


def test_retrieval_metrics_use_metric_and_dimension_labels() -> None:
    """Recall and nDCG account for all requested evidence, not just the first hit."""
    scores = retrieval_scores(["other", "metric:net_revenue", "dimension:category"],
                              {"metric:net_revenue", "dimension:category"}, 2)
    assert scores["recall_at_k"] == .5 and scores["mrr"] == .5
    assert 0 < scores["ndcg_at_k"] < 1
    assert retrieval_scores([], set(), 6)["mrr"] is None
    case = {"expected_metric_id": "net_revenue", "dimensions": ["category"], "filters": [], "grain": "month", "category": "grouped"}
    assert relevant_chunks(case, {"metric:net_revenue", "dimension:category", "dimension:month"}) == {"metric:net_revenue", "dimension:category", "dimension:month"}
    ambiguous = {**case, "category": "ambiguous", "expected_metric_id": None,
                 "question": "Net revenue by region", "dimensions": [], "grain": "total"}
    approved = {"metric:net_revenue", "metric:gross_revenue", "dimension:order_region", "dimension:customer_region"}
    assert relevant_chunks(ambiguous, approved) == approved-{"metric:gross_revenue"}


def test_validator_benchmark_exposes_gaps_without_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DB execution or model call is needed to measure the SQL validator."""
    import sqlite3
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("Probe executed SQL"))
    result = benchmark_validator(ROOT/"eval"/"validator_queries.yaml")
    assert result["bad_count"] >= 25 and result["benign_count"] >= 10
    assert result["llm_calls"] == 0 and result["false_positive_rate"] == 0
    missing = next(r for r in result["cases"] if r["id"] == "missing_formula")
    assert missing["rejected"]
    assert result["catch_rate"] == 1


def test_percentiles_and_empty_aggregation() -> None:
    """Small and empty runs have explicit denominators and interpolated latency."""
    assert percentile([0, 10], .95) == 9.5
    assert percentile([], .5) is None
    assert aggregate([], True)["questions"] == 0


def test_oracle_never_reads_verified_numeric_answer() -> None:
    """Canonical arguments exercise SQL rather than returning expected numbers."""
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    case = next(c for c in cases if c["expected_metric_id"] == "net_revenue")
    altered = {**case, "verified_answer": [{"net_revenue": -999999}]}
    assert OracleModel(case).select().arguments == OracleModel(altered).select().arguments


def test_retrieval_only_never_calls_language_model(warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real retrieval probe with a stub embedder never enters selection or grading."""
    import app.evaluation.runner as runner
    from tests.test_service import FakeModel, service
    app = service(warehouse, tmp_path, FakeModel())
    monkeypatch.setattr(runner, "create_service", lambda _: app)
    monkeypatch.setattr(app, "ask", lambda _: pytest.fail("Retrieval-only entered answer pipeline"))
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    rows = runner.evaluate_mode(app.settings, cases[:2], False, True, Ledger({}, Decimal(0)))
    assert len(rows) == 2 and all("outcome" not in r for r in rows)


def test_offline_pipeline_scores_independent_sql(warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub-embedder replay executes production SQL and scores independent reference rows."""
    import app.evaluation.runner as runner
    from tests.test_service import FakeModel, service
    app = service(warehouse, tmp_path, FakeModel())
    app.settings = app.settings.model_copy(update={"llm_cache_dir": tmp_path/"llm_cache"})
    monkeypatch.setattr(runner, "create_service", lambda _: app)
    _, cases = load_cases(ROOT/"eval"/"questions.yaml", DATABASE_PATH)
    case = next(c for c in cases if c["id"] == "simple-01")
    rows = runner.evaluate_mode(app.settings, [case], False, False, Ledger({}, Decimal(0)))
    assert rows[0]["answer_exact"] and rows[0]["outcome_ok"]
    assert rows[0]["model_sources"] == ["oracle", "oracle"]
    assert rows[0]["cost_usd"] == 0


def test_raw_response_cache_retains_malformed_paid_outputs(warehouse: Path, tmp_path: Path) -> None:
    """Even invalid tool responses replay without contacting the mocked transport."""
    import httpx
    from openai import OpenAI
    from app.llm.client import OpenAIAdapter, _usage
    from app.semantic.loader import load_catalog
    calls = []
    def handler(request: Any) -> Any:
        calls.append(request)
        return httpx.Response(200, json={"id": "resp_stub", "created_at": 0, "object": "response",
            "model": "stub", "output": [], "parallel_tool_calls": False,
            "tool_choice": "required", "tools": [],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})
    with OpenAI(api_key="test-placeholder", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        adapter = OpenAIAdapter(Settings(llm_cache_dir=tmp_path), client)
        adapter.transport_cache = True
        catalog = load_catalog(database=warehouse)
        for _ in range(2):
            with pytest.raises(ValueError, match="exactly one approved"):
                adapter.select("Net revenue", [], catalog)
        assert len(calls) == 1
        assert len(list((tmp_path/"responses").glob("*.json"))) == 1
        response = adapter._response(model="stub", input="different prompt", max_output_tokens=10)
        assert _usage(response)["input_tokens"] == 10
        replay = adapter._response(model="stub", input="different prompt", max_output_tokens=10)
        assert _usage(replay)["input_tokens"] == 0 and _usage(replay)["cache_hit"] == 1
        assert len(calls) == 2
