"""Bounded local-only corrective retrieval before any function selection."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading
from typing import Any, Callable

import streamlit as st

from app.config import Settings
from app.llm.schemas import FUNCTION_MODELS, SelectMetric
from app.observability.trace import Trace
from app.retrieval.budget import BudgetExceeded, BudgetedModel, CallBudget
from app.retrieval.chunks import Hit
from app.retrieval.engine import RetrievalEngine
from app.retrieval.evidence import Judgement, catalog_flags, combine_grade, matching_metrics, requested_dimensions
from app.retrieval.fidelity import faithful_rewrite
from app.retrieval.rerank import Reranker
from app.semantic.models import Catalog
from app.semantic.policy import PolicyError, ambiguity_options, validate_request


@st.cache_resource(show_spinner=False)
def _retrieval_worker() -> tuple[ThreadPoolExecutor,threading.BoundedSemaphore]:
    return ThreadPoolExecutor(max_workers=1,thread_name_prefix="bounded-retrieval"),threading.BoundedSemaphore(1)


def bounded_retrieve(operation: Callable[[],list[Hit]], timeout: float) -> list[Hit]:
    """Bound retrieval waiting time and prevent a queue of timed-out native jobs."""
    executor,slot = _retrieval_worker()
    if not slot.acquire(blocking=False):
        raise BudgetExceeded("Retrieval is busy; retry after the current local operation finishes.")
    future = executor.submit(operation)
    future.add_done_callback(lambda _:slot.release())
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        raise BudgetExceeded("Retrieval timed out; no evidence was accepted.") from None


class CorrectiveController:
    """At most two retrieval rounds and one rewrite OR local correction attempt."""

    def __init__(self, catalog: Catalog, engine: RetrievalEngine, settings: Settings, reranker: Reranker | None) -> None:
        self.catalog,self.engine,self.settings,self.reranker = catalog,engine,settings,reranker

    def _rank(self, question: str, hits: list[Hit], trace: Trace, budget: CallBudget) -> list[Hit]:
        with trace.step("reranking") as event:
            event["enabled"] = self.settings.rerank_enabled
            if self.settings.rerank_enabled:
                if self.reranker is None:
                    raise PolicyError("refuse","Reranker unavailable. Check RERANK_MODEL or RERANK_ENABLED.")
                hits = self.reranker.rerank(question,hits,self.settings.evidence_k,
                    min(self.settings.rerank_timeout,budget.remaining_seconds()))
            else:
                hits = hits[:self.settings.evidence_k]
            event["candidates"] = [hit.as_dict() for hit in hits]
        return hits

    def prepare(self, question: str, trace: Trace, model: BudgetedModel, budget: CallBudget) -> list[Hit]:
        """Retrieve, rerank, grade, then proceed, clarify or abstain within fixed bounds."""
        query = question
        corrected = False
        correction_targets = []
        resolved_metric_id = None
        for round_index in range(self.settings.max_retrieval_rounds):
            with trace.step("retrieval" if round_index==0 else "correction_retrieval") as event:
                hits = bounded_retrieve(lambda:self.engine.candidates(query,self.settings.candidate_k),
                    min(self.settings.retrieval_timeout,budget.remaining_seconds()))
                if corrected:
                    # Pull explicit named definitions from approved corpus only.
                    existing = {h.chunk.id:h for h in hits}
                    additions = []
                    for chunk in correction_targets:
                        previous = existing.get(chunk.id)
                        additions.append(Hit(chunk,previous.score if previous else 0.0,
                            {**(previous.ranks if previous else {}),"catalog_correction":1},
                            {**(previous.scores if previous else {}),"catalog_correction":1.0}))
                    target_ids = {h.chunk.id for h in additions}
                    hits = [*additions,*(h for h in hits if h.chunk.id not in target_ids)][:self.settings.candidate_k]
                event.update(round=round_index+1,candidates=[h.as_dict() for h in hits],
                    top_metric=next((h.chunk.metadata.get("metric_id") for h in hits if h.chunk.kind=="metric"),None),
                    tokens=dict(self.engine.tokens),source="approved_local_catalog")
            candidates = {h.chunk.id:h for h in hits}
            hits = self._rank(query,hits,trace,budget)
            if corrected and resolved_metric_id:
                # Exact lookup during correction must retain the validated metric
                # definition even when a cross-encoder favors related prose/rules.
                required = candidates.get("metric:"+resolved_metric_id)
                if required and all(h.chunk.id != required.chunk.id for h in hits):
                    hits = [*hits[:max(0,self.settings.evidence_k-1)],required]
            with trace.step("evidence_selection") as event:
                event["selected"] = [h.chunk.id for h in hits]
                event["candidates"] = [h.as_dict() for h in hits]
                event["protected_metric_id"] = resolved_metric_id if corrected else None
            if self.settings.rag_mode=="hybrid_rerank":
                with trace.step("final_decision") as event:
                    event["decision"] = "proceed_to_function_call"
                return hits
            # Exact lexical matching is a retrieval baseline, not an intent gate.
            # Resolve unfamiliar wording once through the SAME three governed tools,
            # then validate before allowing that ID to inform evidence grading.
            if (round_index == 0 and not matching_metrics(question,self.catalog)
                    and not ambiguity_options(question,self.catalog)):
                with trace.step("intent_resolution") as event:
                    call = model.select(question,hits,self.catalog)
                    event.update(function=call.name,arguments=call.arguments,tokens=call.tokens)
                    schema = FUNCTION_MODELS.get(call.name)
                    if schema is None:
                        raise PolicyError("refuse","The model selected an unapproved function.")
                    arguments = schema.model_validate(call.arguments)
                    if call.name == "refuse":
                        raise PolicyError("refuse",arguments.reason)
                    if call.name == "request_clarification":
                        raise PolicyError("clarify","Choose the intended catalog definition.",arguments.options)
                    assert isinstance(arguments,SelectMetric)
                    valid = validate_request(arguments,self.catalog)
                    resolved_metric_id = valid.metric.id
                    event.update(validated=True,metric_id=resolved_metric_id)
            with trace.step("grading") as event:
                options = ambiguity_options(question,self.catalog)
                if options or len(matching_metrics(question,self.catalog))>1:
                    judgement = Judgement(verdict="conflicting",confidence=1.0,missing_aspects=[],conflicts=options or matching_metrics(question,self.catalog))
                    event["source"] = "catalog_ambiguity"
                elif not all(catalog_flags(question,hits,self.catalog,resolved_metric_id)[name] for name in ("metric_found","dimension_allowed","time_grain_valid")):
                    judgement = Judgement(verdict="insufficient",confidence=1.0,missing_aspects=[],conflicts=[])
                    event["source"] = "deterministic_catalog_checks"
                else:
                    event["tokens"] = {}
                    judgement,tokens = model.judge(question,hits,self.catalog,resolved_metric_id)
                    event["tokens"] = tokens
                    event["source"] = "structured_model_judgement"
                grade = combine_grade(question,hits,self.catalog,judgement,self.settings.evidence_confidence,resolved_metric_id)
                if round_index+1>=self.settings.max_retrieval_rounds:
                    if grade.verdict=="insufficient":
                        grade.next_action = "abstain"
                    elif grade.verdict=="ambiguous":
                        grade.next_action = "clarify"
                event["grade"] = grade.model_dump()
            budget.remaining_seconds()
            if grade.next_action=="proceed":
                with trace.step("final_decision") as event:
                    event.update(decision="proceed",grade=grade.model_dump())
                return hits
            if grade.verdict=="conflicting":
                choices = list(dict.fromkeys([*options,*matching_metrics(question,self.catalog),
                    *(name for conflict in judgement.conflicts for name in matching_metrics(conflict,self.catalog))]))
                with trace.step("correction") as event:
                    # Keyed lookup rather than a network/extra model request.
                    definitions = [c for c in self.engine.lookup.chunks if c.metadata.get("metric_id") in choices or c.metadata.get("dimension_id") in choices]
                    event.update(source="approved_local_catalog",competing_definitions=[c.id for c in definitions])
                self._stop(trace,"clarify",choices if len(choices)>=2 else ["Use the governed definition","Clarify the requested distinction"])
            if round_index+1>=self.settings.max_retrieval_rounds:
                self._stop(trace,"clarify" if grade.verdict=="ambiguous" else "refuse",
                    ["Specify the metric and dimensions","Choose a catalog definition"] if grade.verdict=="ambiguous" else [])
            if grade.verdict=="ambiguous":
                with trace.step("rewriting") as event:
                    event["tokens"] = {}
                    faithful = False
                    try:
                        rewrite,tokens = model.rewrite(question,hits,self.catalog)
                        event["tokens"] = tokens
                        faithful = faithful_rewrite(question,rewrite.query,self.catalog)
                        event.update(fidelity_passed=faithful,query=rewrite.query if faithful else "Rejected rewrite")
                    except Exception as error:
                        event.update(fidelity_passed=False,error_type=type(error).__name__)
                if not faithful:
                    self._stop(trace,"clarify",["Specify the intended metric","Specify the requested scope"])
                query = rewrite.query
            else:
                with trace.step("correction") as event:
                    named = set(matching_metrics(question,self.catalog))
                    if resolved_metric_id:
                        named.add(resolved_metric_id)
                    dimensions = requested_dimensions(question,self.catalog)
                    correction_targets = [c for c in self.engine.lookup.chunks if c.metadata.get("metric_id") in named
                        or c.metadata.get("dimension_id") in dimensions or bool(set(c.metadata.get("metric_ids",[])) & named)]
                    event.update(source="approved_local_catalog",attempt=1,missing_aspects=grade.missing_aspects,
                        targets=[c.id for c in correction_targets])
                corrected = True
        self._stop(trace,"refuse",[])
        return []

    @staticmethod
    def _stop(trace: Trace, outcome: str, options: list[str]) -> None:
        with trace.step("final_decision") as event:
            event.update(decision="clarify" if outcome=="clarify" else "abstain",outcome=outcome)
        raise PolicyError(outcome,"Evidence is ambiguous; choose the intended definition." if outcome=="clarify"
            else "Sufficient governed evidence could not be established within the correction limit.",options)
