"""Question-to-answer orchestration with explicit safety layers and fail-closed SQL."""

from typing import Any
from uuid import UUID
import sqlite3
from openai import APITimeoutError, RateLimitError

from pydantic import ValidationError

from app.answers.calculator import calculate
from app.answers.render import fallback_template, render, result_fields
from app.config import CATALOG_PATH, Settings
from app.db.executor import execute_query
from app.llm.client import LanguageModel, OpenAIAdapter
from app.llm.cache import CachedLanguageModel
from app.llm.schemas import FUNCTION_MODELS, SelectMetric, ToolCall
from app.observability.contracts import PipelineResponse
from app.observability.trace import Trace, redact
from app.retrieval.chunks import chunk_catalog
from app.retrieval.dense import DenseRetriever
from app.retrieval.engine import RetrievalEngine
from app.retrieval.index import load_catalog_index
from app.observability.startup import startup_step
from app.retrieval.providers import EmbeddingUnavailableError, create_embedder
from app.retrieval.budget import BudgetExceeded, BudgetedModel, CallBudget
from app.retrieval.control import CorrectiveController, bounded_retrieve
from app.retrieval.rerank import LocalCrossEncoder, Reranker, RerankUnavailable
from app.semantic.loader import load_catalog
from app.semantic.models import Catalog
from app.semantic.policy import PolicyError, ambiguity_options, metric_exists, validate_request
from app.sql.compiler import compile_request
from app.sql.validation import validate_query


class MetricsService:
    """Run independently injectable retrieval, selection, execution and rendering stages."""

    def __init__(self, catalog: Catalog, settings: Settings, retrieval: RetrievalEngine, model: LanguageModel, reranker: Reranker | None = None) -> None:
        self.catalog,self.settings,self.retrieval,self.model = catalog,settings,retrieval,model
        self.reranker = reranker

    def ask(self, question: str) -> PipelineResponse:
        """Answer a question or return an explicit clarify/refuse/empty_result outcome."""
        trace = Trace(self.settings.trace_dir)
        budget = CallBudget(self.settings.max_llm_calls,self.settings.max_output_tokens,self.settings.request_timeout)
        model = BudgetedModel(self.model,budget,self.settings)
        response = PipelineResponse(outcome="refuse",value=None,metric_definition=None,sql=None,trace_id=UUID(trace.request_id))
        try:
            with trace.step("question_received") as event:
                if not isinstance(question,str) or not question.strip() or len(question)>4000:
                    raise PolicyError("clarify","Enter a question within the supported length.",["Ask for a governed metric","Choose a metric from the catalog"])
                question = redact(question)
                event["question"] = question
                event["rag_mode"] = self.settings.rag_mode
                event["embedding_provider"] = self.settings.embedding_provider
                event["embedding_model"] = self.settings.embedding_model
            if self.settings.rag_mode in {"hybrid_rerank","corrective"}:
                hits = CorrectiveController(self.catalog,self.retrieval,self.settings,self.reranker).prepare(question,trace,model,budget)
                response.retrieved = [h.as_dict() for h in hits]
            else:
                with trace.step("retrieval") as event:
                    event["tokens"] = {}
                    hits = bounded_retrieve(lambda:self.retrieval.search(question,self.settings.rag_mode,self.settings.top_k),
                        min(self.settings.retrieval_timeout,budget.remaining_seconds()))
                    event["candidates"] = [h.as_dict() for h in hits]
                    event["top_metric"] = next((h.chunk.metadata.get("metric_id") for h in hits if h.chunk.kind=="metric"),None)
                    event["tokens"] = {"input_tokens":0,"output_tokens":0,"total_tokens":0,**self.retrieval.tokens}
                    response.retrieved = event["candidates"]
            options = ambiguity_options(question,self.catalog)
            if options:
                with trace.step("ambiguity_check") as event:
                    event["options"] = options
                raise PolicyError("clarify","Choose the intended metric or region definition.",options)
            with trace.step("function_call") as event:
                event["tokens"] = {}
                resolution = next((e for e in trace.events if e["step"]=="intent_resolution" and e.get("validated")),None)
                call = ToolCall(resolution["function"],resolution["arguments"]) if resolution else model.select(question,hits,self.catalog)
                event["source"] = "validated_intent_reuse" if resolution else "model"
                event.update(function=call.name,arguments=call.arguments,tokens=call.tokens)
            with trace.step("argument_validation") as event:
                schema = FUNCTION_MODELS.get(call.name)
                if schema is None:
                    raise PolicyError("refuse","The model selected an unapproved function.")
                arguments = schema.model_validate(call.arguments)
                event["validated"] = True
            if call.name == "request_clarification":
                response.outcome = "clarify"
                response.options = arguments.options
                response.text = "Choose an option to clarify your question."
                return response
            if call.name == "refuse":
                response.text = arguments.reason
                return response
            assert isinstance(arguments,SelectMetric)
            budget.remaining_seconds()
            with trace.step("catalog_metric_check") as event:
                metric = metric_exists(arguments,self.catalog)
                event["metric_id"] = metric.id
                response.metric_definition = metric.description+" "+" ".join(metric.business_rules)
            with trace.step("allow_list_validation") as event:
                validated = validate_request(arguments,self.catalog)
                if self.settings.rag_mode=="corrective":
                    accepted = next((e["grade"]["metric_id"] for e in reversed(trace.events)
                        if e["step"]=="grading" and e.get("grade",{}).get("next_action")=="proceed"),None)
                    if accepted != arguments.metric_id:
                        raise PolicyError("refuse","The selected metric does not match the accepted catalog evidence.")
                event.update(start=validated.start,end=validated.end,dimensions=arguments.dimensions,grain=arguments.grain)
            with trace.step("sql_compile") as event:
                query = compile_request(validated,self.catalog,self.settings.max_rows,include_components=True)
                response.sql,response.parameters = query.sql,query.parameters
                event.update(sql=query.sql,parameters=query.parameters)
            with trace.step("sql_validation") as event:
                validate_query(query.sql,query.max_rows)
                event["validated"] = True
            with trace.step("db_execution") as event:
                rows = execute_query(query,self.settings.database,self.settings.query_timeout)
                response.rows = rows
                event["row_count"] = len(rows)
                event["row_limit"] = self.settings.max_rows
            if not rows:
                response.outcome,response.text = "empty_result","No matching result was found for this valid query."
                with trace.step("answer_generation") as event:
                    event["source"] = "deterministic_empty_result"
                return response
            with trace.step("answer_generation") as event:
                event["tokens"] = {}
                calculations = calculate(rows,metric.id,metric.unit,query.dimensions)
                if metric.id == "aov":
                    for index,row in enumerate(rows):
                        row[metric.id] = calculations[f"row{index}_per_order"]
                # Auxiliary SQL operands are query-sourced calculator inputs, not UI columns.
                rows = [{key:value for key,value in row.items() if not key.startswith("__")} for row in rows]
                response.rows = rows
                fields = result_fields(rows,metric.id)
                response.calculations = calculations
                payload = {"question":question,"metric":metric.display_name,"definition":metric.description,
                    "unit":metric.unit,"result":fields,"calc":calculations,
                    "scope_note":"Results are limited to the configured row cap; visible shares refer only to returned groups."}
                response.template_source = "model"
                try:
                    template,tokens = model.answer(payload)
                    event["tokens"] = tokens
                    text = render(template.template,fields,calculations)
                except Exception as error:
                    # A safe deterministic renderer fallback, never a retrieval retry.
                    from app.answers.render import AnswerTemplate
                    template = AnswerTemplate(template=fallback_template(rows,metric.id))
                    text = render(template.template,fields,calculations)
                    response.template_source = "deterministic"
                    event["fallback_reason"] = type(error).__name__
                response.template,response.text = template.template,text
                event["source"] = response.template_source
            response.value = rows[0][metric.id] if len(rows)==1 and not query.dimensions else rows
            response.outcome = "answer"
        except PolicyError as error:
            response.outcome = error.outcome
            response.text,response.options = str(error),error.options
        except (EmbeddingUnavailableError,RerankUnavailable,BudgetExceeded) as error:
            response.outcome,response.text = "refuse",str(error)
        except ValidationError:
            response.outcome,response.text = "refuse","The function arguments failed validation."
            if trace.events and trace.events[-1]["step"] in {"grading","rewriting"}:
                response.text = "Structured evidence or rewrite validation failed; no query was executed."
        except (APITimeoutError,TimeoutError):
            response.outcome,response.text = "refuse","The language-model request timed out. Please retry later."
        except RateLimitError:
            response.outcome,response.text = "refuse","The language-model rate limit was reached. Please retry later."
        except sqlite3.Error:
            response.outcome,response.text = "refuse","The database query could not be completed. Please retry or check database availability."
        except Exception as error:
            # Never echo provider exceptions, credentials or model-generated SQL.
            response.outcome,response.text = "refuse","The request could not be completed safely. Check configuration or the trace timeline."
        finally:
            if self.settings.rag_mode in {"hybrid_rerank","corrective"}:
                decisions = [e for e in trace.events if e["step"]=="final_decision"]
                if not decisions or (response.outcome=="refuse" and decisions[-1].get("decision") in {"proceed","proceed_to_function_call"}):
                    with trace.step("final_decision") as event:
                        event.update(decision="abstain",outcome=response.outcome)
                response.crag_path = [e["step"] for e in trace.events if e["step"] in {
                    "retrieval","reranking","intent_resolution","grading","rewriting","correction","correction_retrieval","evidence_selection","final_decision"}]
                response.evidence_grades = [e["grade"] for e in trace.events if e["step"]=="grading" and "grade" in e]
                if not response.retrieved:
                    response.retrieved = next((e["candidates"] for e in reversed(trace.events) if "candidates" in e),[])
            response.model_calls = budget.calls
            response.output_token_reservation = budget.reserved_tokens
            response.text = redact(response.text)
            response.options = redact(response.options)
            # The UI exposes the full response, not just prose. Scrub every public
            # presentation field, including templates, evidence and bound literals.
            for name in type(response).model_fields:
                if name not in {"outcome","trace_id"}:
                    value = getattr(response,name)
                    if isinstance(value,(str,list,dict,tuple)):
                        setattr(response,name,redact(value))
            response.latency_ms = trace.save(response.outcome)
            response.trace = trace.events
        return response


class _LazyOpenAI:
    """Defer credential checking until a traced API step actually needs the client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adapter: OpenAIAdapter | None = None
        self.deadline: float | None = None

    def _get(self) -> OpenAIAdapter:
        if self.adapter is None:
            self.adapter = OpenAIAdapter(self.settings)
        self.adapter.deadline = self.deadline
        return self.adapter

    def select(self, *args: Any) -> Any:
        """Delegate the function-call request."""
        return self._get().select(*args)

    def answer(self, *args: Any) -> Any:
        """Delegate the structured answer request."""
        return self._get().answer(*args)

    def embed(self, texts: list[str]) -> Any:
        """Delegate catalog/query embedding requests."""
        return self._get().embed(texts)

    def set_deadline(self, deadline: float) -> None:
        """Apply the current request deadline to each provider call."""
        self.deadline = deadline

    def judge(self, *args: Any) -> Any:
        """Delegate structured evidence judgement."""
        return self._get().judge(*args)

    def rewrite(self, *args: Any) -> Any:
        """Delegate a bounded retrieval-only rewrite."""
        return self._get().rewrite(*args)


def create_service(settings: Settings) -> MetricsService:
    """Build the real API-backed application without making any API calls yet."""
    catalog,chunks = load_catalog_index(str(settings.database.resolve()),
        settings.database.stat().st_mtime_ns,CATALOG_PATH.stat().st_mtime_ns)
    client = CachedLanguageModel(settings,delegate=_LazyOpenAI(settings))
    startup_step("Preparing embedder (model loading is deferred until retrieval)")
    embedder = create_embedder(settings,client)
    dense = DenseRetriever(chunks,embedder,settings.embedding_model,settings.cache_dir)
    reranker = Reranker(LocalCrossEncoder(settings.rerank_model,settings.model_cache_dir,settings.rerank_batch_size),
        settings.rerank_model,settings.cache_dir.parent/"rerank_cache")
    return MetricsService(catalog,settings,RetrievalEngine(chunks,dense),client,reranker)
