"""Reranking and bounded corrective control using stub local/model scorers only."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.retrieval.budget import BudgetExceeded, CallBudget
from app.retrieval.chunks import Hit
from app.retrieval.evidence import EvidenceGrade, Judgement, Rewrite, catalog_flags, combine_grade
from app.retrieval.external import DisabledExternalSource
from app.retrieval.fidelity import faithful_rewrite
from app.retrieval.rerank import Reranker
from app.llm.schemas import ToolCall
from tests.test_pipeline_safety import arguments
from tests.test_service import FakeModel, service


class StubPairScorer:
    """Explicit deterministic pair scores, not a production cross-encoder substitute."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, question: str, passages: list[str], timeout: float) -> list[float]:
        """Prefer net-revenue definitions for predictable controller tests."""
        self.calls += 1
        return [100.0 if text.startswith("Net revenue\n") else 1.0 for text in passages]


class CorrectiveModel(FakeModel):
    """Script evidence judgements without network calls or metric arithmetic."""

    def __init__(self, verdicts: list[str]) -> None:
        super().__init__()
        self.verdicts = verdicts
        self.judgements,self.rewrites = 0,0

    def judge(self, *args: Any) -> tuple[Judgement,dict[str,int]]:
        """Return an authored semantic verdict; never return catalog booleans."""
        verdict = self.verdicts[min(self.judgements,len(self.verdicts)-1)]
        self.judgements += 1
        return Judgement(verdict=verdict,confidence=0.9,missing_aspects=[],conflicts=[]),{}

    def rewrite(self, question: str, *args: Any) -> tuple[Rewrite,dict[str,int]]:
        """Append only a synonym of the explicit metric for the safe rewrite path."""
        self.rewrites += 1
        return Rewrite(query=question+" net sales"),{}


def corrective_app(warehouse: Path, tmp_path: Path, model: CorrectiveModel, **updates: Any):
    """Create a real warehouse pipeline with deterministic retrieval and pair scoring."""
    app = service(warehouse,tmp_path,model)
    app.settings = app.settings.model_copy(update={"rag_mode":"corrective",**updates})
    app.reranker = Reranker(StubPairScorer(),"stub-cross",tmp_path/"scores")
    return app


def test_reranking_changes_order_and_caches(warehouse: Path, tmp_path: Path) -> None:
    """Pair scores override fusion order and repeated pairs require no new inference."""
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]))
    chunks = app.retrieval.lookup.chunks
    net = next(c for c in chunks if c.id=="metric:net_revenue")
    other = next(c for c in chunks if c.id=="metric:orders")
    hits = [Hit(other,10,{"dense":1},{"dense":10}),Hit(net,1,{"dense":2},{"dense":1})]
    ranked = app.reranker.rerank("net revenue",hits)
    assert ranked[0].chunk==net and ranked[0].ranks["dense"]==2
    assert app.reranker.scorer.calls==1
    app.reranker.rerank("net revenue",hits)
    assert app.reranker.scorer.calls==1


def test_candidate_pool_unique_dense_bm25(warehouse: Path, tmp_path: Path) -> None:
    """New modes use bounded dense/BM25 fusion, with no lookup-scoring contribution."""
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]))
    hits = app.retrieval.candidates("net revenue",25)
    assert len(hits)==25 and len({h.chunk.id for h in hits})==25
    assert all(set(h.ranks)<={"dense","bm25"} for h in hits)
    assert len(app.retrieval.candidates("net revenue",100))==len(app.retrieval.lookup.chunks)


def test_sufficient_path(warehouse: Path, tmp_path: Path) -> None:
    """Sufficient evidence proceeds to the unchanged function/SQL safety chain."""
    model = CorrectiveModel(["sufficient"])
    result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="answer" and result.model_calls==3
    assert result.evidence_grades[0]["metric_found"] is True
    assert result.evidence_grades[0]["next_action"]=="proceed"
    assert len(result.retrieved)<=10 and "grading" in result.crag_path
    assert model.selections==1 and model.questions==["Show net revenue."]


def test_correction_triggers_then_succeeds(warehouse: Path, tmp_path: Path) -> None:
    """One local-catalog correction can recover insufficient evidence and proceed."""
    model = CorrectiveModel(["insufficient","sufficient"])
    result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="answer" and result.model_calls==4
    assert "correction" in result.crag_path and "correction_retrieval" in result.crag_path
    assert len(result.evidence_grades)==2 and model.judgements==2


def test_conflicting_definitions_clarify(warehouse: Path, tmp_path: Path) -> None:
    """Known gross/net ambiguity retrieves competing definitions without an API call."""
    model = CorrectiveModel(["sufficient"])
    result = corrective_app(warehouse,tmp_path,model).ask("What is revenue?")
    assert result.outcome=="clarify" and set(result.options)=={"gross_revenue","net_revenue"}
    assert result.model_calls==0 and model.selections==0
    correction = next(e for e in result.trace if e["step"]=="correction")
    assert set(correction["competing_definitions"])=={"metric:gross_revenue","metric:net_revenue"}


def test_failed_correction_abstains(warehouse: Path, tmp_path: Path) -> None:
    """Repeated insufficient judgements stop after the second round, without SQL."""
    model = CorrectiveModel(["insufficient"])
    result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="refuse" and result.sql is None and model.selections==0
    assert len(result.evidence_grades)==2
    assert result.evidence_grades[-1]["next_action"]=="abstain"
    assert sum(e["step"]=="correction" for e in result.trace)==1


def test_one_rewrite_then_original_question_selection(warehouse: Path, tmp_path: Path) -> None:
    """Query expansion is retrieval-only; function selection sees original user intent."""
    model = CorrectiveModel(["ambiguous","sufficient"])
    result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="answer" and model.rewrites==1 and result.model_calls==4
    assert result.template_source=="deterministic"  # answer call cannot exceed the cap
    assert model.questions==["Show net revenue."]


@pytest.mark.parametrize("rewrite",["Show gross revenue.","Show net revenue in 2025.",
    "Show net revenue. excluding refunds","Show net revenue. by category","Show net revenue. > 100",
    "Show net revenue. USD","Show net revenue. ; --"])
def test_rewrite_fidelity_rejects_changed_aspects(rewrite: str, warehouse: Path, tmp_path: Path) -> None:
    """Metric/dimension/date/number/unit/negation changes cannot enter a rewrite."""
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]))
    assert not faithful_rewrite("Show net revenue.",rewrite,app.catalog)


def test_catalog_flags_override_model(warehouse: Path, tmp_path: Path) -> None:
    """The model cannot authorize a dimension or time grain through a sufficient verdict."""
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]))
    hits = app.retrieval.candidates("orders",25)
    grade = combine_grade("Show orders by city and category daily",hits,app.catalog,
        Judgement(verdict="sufficient",confidence=1.0,missing_aspects=[],conflicts=[]),0.65)
    assert grade.verdict=="insufficient" and not grade.dimension_allowed and not grade.time_grain_valid
    with pytest.raises(ValidationError):
        Judgement(verdict="looks good",confidence=1.0,missing_aspects=[],conflicts=[])
    with pytest.raises(ValidationError):
        Judgement(verdict="sufficient",confidence=1.0,missing_aspects=[],conflicts=[],metric_found=True)


def test_call_cap_and_round_cap(warehouse: Path, tmp_path: Path) -> None:
    """Tighter operator limits fail closed without hidden retries or corrections."""
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]),max_llm_calls=1)
    result = app.ask("Show net revenue.")
    assert result.outcome=="refuse" and result.model_calls==1
    app = corrective_app(warehouse,tmp_path,CorrectiveModel(["insufficient"]),max_retrieval_rounds=1)
    result = app.ask("Show net revenue.")
    assert result.outcome=="refuse" and len(result.evidence_grades)==1
    assert "correction_retrieval" not in result.crag_path


def test_reranking_disabled_and_hybrid_rerank(warehouse: Path, tmp_path: Path) -> None:
    """Rerank disabling is explicit and the rerank-only mode spends no grading calls."""
    model = CorrectiveModel(["sufficient"])
    app = corrective_app(warehouse,tmp_path,model,rag_mode="hybrid_rerank",rerank_enabled=False)
    result = app.ask("Show net revenue.")
    assert result.outcome=="answer" and model.judgements==0
    assert next(e for e in result.trace if e["step"]=="reranking")["enabled"] is False


def test_external_disabled_and_token_budget() -> None:
    """No external source can be fetched and reservations include failed attempts."""
    with pytest.raises(RuntimeError,match="disabled"):
        DisabledExternalSource().search("unknown")
    budget = CallBudget(2,100,10)
    budget.take(80)
    with pytest.raises(BudgetExceeded):
        budget.take(30)
    assert budget.calls==1


def test_selection_cannot_override_accepted_metric(warehouse: Path, tmp_path: Path) -> None:
    """A valid catalog ID is still refused if it contradicts accepted evidence."""
    model = CorrectiveModel(["sufficient"])
    model.call = ToolCall("select_metric",arguments("gross_revenue").model_dump())
    result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="refuse" and result.sql is None
    assert "accepted catalog evidence" in result.text


def test_failed_rewrite_clarifies(warehouse: Path, tmp_path: Path) -> None:
    """An invalid or unavailable rewrite cannot replace ambiguity with a guessed answer."""
    from unittest.mock import patch
    model = CorrectiveModel(["ambiguous"])
    with patch.object(model,"rewrite",side_effect=ValueError("private failure detail")):
        result = corrective_app(warehouse,tmp_path,model).ask("Show net revenue.")
    assert result.outcome=="clarify" and result.sql is None
    assert "private failure detail" not in result.text
