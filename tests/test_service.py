"""Full pipeline tests using real SQLite and injected deterministic model outputs."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.answers.render import AnswerTemplate
from app.config import Settings
from app.llm.schemas import ToolCall
from app.retrieval.chunks import chunk_catalog
from app.retrieval.dense import DenseRetriever
from app.retrieval.engine import RetrievalEngine
from app.retrieval.providers import OpenAIEmbedder
from app.semantic.loader import load_catalog
from app.service import MetricsService
from tests.test_pipeline_safety import arguments
from tests.test_retrieval import FakeEmbeddings


class FakeModel:
    """Inject a selected function and reference-only answer without network access."""

    def __init__(self, call: ToolCall | None = None, template: str | None = None) -> None:
        self.call = call or ToolCall("select_metric",arguments().model_dump())
        self.template = template or "Net revenue is {{result.net_revenue}}."
        self.selections = 0
        self.questions: list[str] = []

    def select(self, question: str, candidates: list, catalog: Any) -> ToolCall:
        """Return one specified untrusted model selection."""
        self.selections += 1
        self.questions.append(question)
        return self.call

    def answer(self, payload: dict) -> tuple[AnswerTemplate,dict[str,int]]:
        """Return a specified template to test provenance enforcement."""
        return AnswerTemplate(template=self.template),{"input_tokens":10,"output_tokens":5}


def service(warehouse: Path, temporary: Path, model: FakeModel, mode: str = "lookup") -> MetricsService:
    """Create an isolated service with real catalog/DB and fake provider clients."""
    catalog = load_catalog(database=warehouse)
    settings = Settings(database=warehouse,trace_dir=temporary/"traces",cache_dir=temporary/"cache",rag_mode=mode)
    chunks = chunk_catalog(catalog)
    dense = DenseRetriever(chunks,FakeEmbeddings(),"test",settings.cache_dir)
    return MetricsService(catalog,settings,RetrievalEngine(chunks,dense),model)


@pytest.mark.parametrize("mode",["lookup","naive","hybrid"])
def test_end_to_end_answer(mode: str, warehouse: Path, tmp_path: Path) -> None:
    """All modes traverse the full safety chain and render query-sourced values."""
    result = service(warehouse,tmp_path,FakeModel(),mode).ask("What is net revenue?")
    assert result.outcome=="answer" and result.value>0
    assert result.metric_definition and result.sql and result.trace_id
    assert str(result.value) in result.text
    steps = [event["step"] for event in result.trace]
    assert steps == ["question_received","retrieval","function_call","argument_validation","catalog_metric_check",
        "allow_list_validation","sql_compile","sql_validation","db_execution","answer_generation"]
    assert all(event["latency_ms"]>=0 and "tokens" in event for event in result.trace)
    record = json.loads((tmp_path/"traces"/"requests.jsonl").read_text())
    assert record["request_id"] == str(result.trace_id)


@pytest.mark.parametrize("question",["What is revenue?","Show gross revenue by region"])
def test_ambiguity_before_model(question: str, warehouse: Path, tmp_path: Path) -> None:
    """Ambiguities cannot be silently guessed by the selector model."""
    model = FakeModel()
    result = service(warehouse,tmp_path,model).ask(question)
    assert result.outcome=="clarify" and result.options
    assert model.selections==0 and result.sql is None


@pytest.mark.parametrize("call,expected",[
    (ToolCall("select_metric",arguments("nonexistent").model_dump()),"refuse"),
    (ToolCall("select_metric",arguments("orders",dimensions=["category"]).model_dump()),"refuse"),
    (ToolCall("select_metric",arguments(filters=[{"dimension":"brand","operator":"eq","values":["unknown"]}]).model_dump()),"clarify"),
    (ToolCall("request_clarification",{"options":["gross_revenue","net_revenue"]}),"clarify"),
    (ToolCall("refuse",{"reason":"That metric is undefined."}),"refuse"),
    (ToolCall("execute_sql",{"sql":"SELECT 1"}),"refuse"),
    (ToolCall("select_metric",{**arguments().model_dump(),"sql":"DROP TABLE orders"}),"refuse"),
])
def test_nonanswer_outcomes_do_not_execute(call: ToolCall, expected: str, warehouse: Path, tmp_path: Path) -> None:
    """Policy and schema failures terminate without any data query."""
    with patch("app.service.execute_query") as execute:
        result = service(warehouse,tmp_path,FakeModel(call)).ask("Show the selected metric")
        assert result.outcome==expected and result.value is None
        execute.assert_not_called()


def test_empty_result(warehouse: Path, tmp_path: Path) -> None:
    """A fully valid empty query has its own outcome and retains SQL/definition."""
    call = ToolCall("select_metric",arguments(time_range={"start":"2020-01-01","end":"2020-02-01","relative":None}).model_dump())
    result = service(warehouse,tmp_path,FakeModel(call)).ask("Show net revenue in the selected dates")
    assert result.outcome=="empty_result" and result.value is None
    assert result.sql and result.metric_definition


def test_unsafe_answer_falls_back_without_rag_retry(warehouse: Path, tmp_path: Path) -> None:
    """Raw model numbers are discarded in favor of a deterministic safe template."""
    model = FakeModel(template="Net revenue is 999999999.")
    result = service(warehouse,tmp_path,model).ask("Show net revenue")
    assert result.outcome=="answer" and result.template_source=="deterministic"
    assert "999999999" not in result.text and model.selections==1


def test_trace_redacts_credentials(warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Question/argument tracing cannot persist known environment secrets."""
    secret = "sk-test-secret-abc123"
    monkeypatch.setenv("OPENAI_API_KEY",secret)
    model = FakeModel()
    result = service(warehouse,tmp_path,model).ask("Show net revenue; api_key="+secret)
    text = (tmp_path/"traces"/"requests.jsonl").read_text()
    assert secret not in text and "[REDACTED]" in text
    assert secret not in json.dumps(result.trace)
    assert all(secret not in question for question in model.questions)


def test_embedding_access_failure_is_explicit(warehouse: Path, tmp_path: Path) -> None:
    """Provider permission failures do not silently turn hybrid into lookup."""
    class PermissionDeniedError(RuntimeError):
        """Test-only provider access failure."""
    app = service(warehouse,tmp_path,FakeModel(),"hybrid")
    stub = app.retrieval.dense.provider
    app.retrieval.dense.provider = OpenAIEmbedder(stub)
    with patch.object(stub,"embed",side_effect=PermissionDeniedError("private provider detail")):
        result = app.ask("Show net revenue")
    assert result.outcome == "refuse"
    assert "OPENAI_EMBEDDING_MODEL" in result.text
    assert "private provider detail" not in result.text
    assert not any(event["step"]=="db_execution" for event in result.trace)


def test_aov_per_order_calculator_reference(warehouse: Path, tmp_path: Path) -> None:
    """AOV prose uses an application-calculated ratio of SQL-sourced operands."""
    model = FakeModel(ToolCall("select_metric",arguments("aov").model_dump()),"Per-order value is {{calc.per_order}}.")
    result = service(warehouse,tmp_path,model).ask("What is average order value?")
    assert result.outcome=="answer"
    assert result.calculations["per_order"]==result.value
    assert result.template_source=="model"
    assert "__numerator" not in result.rows[0]
