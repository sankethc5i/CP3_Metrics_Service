"""Clearly labelled canonical-argument replay; not a model-quality measurement."""

from typing import Any

from app.answers.render import AnswerTemplate
from app.llm.schemas import ToolCall
from app.retrieval.evidence import Judgement, Rewrite, catalog_flags


class OracleModel:
    """Exercise production safety and execution using authored selection arguments."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case

    def select(self, *args: Any) -> ToolCall:
        """Replay canonical selection, leaving invalid arguments to real validation."""
        case = self.case
        if case["expected_metric_id"] is None:
            if case["expected_outcome"] == "clarify":
                return ToolCall("request_clarification", {"options": case["clarification_options"]})
            return ToolCall("refuse", {"reason": "The operation or metric is not governed."})
        return ToolCall("select_metric", {"metric_id": case["expected_metric_id"],
            "dimensions": case["dimensions"], "filters": case["filters"],
            "time_range": case["time_range"], "grain": case["grain"]})

    def answer(self, payload: dict[str, Any]) -> tuple[AnswerTemplate, dict[str, int]]:
        """Use field references without reading the expected numeric answer."""
        return AnswerTemplate(template="Returned {{result.row_count}} result groups."), {}

    def judge(self, question: str, hits: list[Any], catalog: Any, resolved_metric_id: str | None = None) -> tuple[Judgement, dict[str, int]]:
        """Use local flags as oracle judgement; semantic LLM quality remains unmeasured."""
        flags = catalog_flags(question, hits, catalog, self.case["expected_metric_id"])
        sufficient = all(flags[k] for k in ("metric_found", "dimension_allowed", "time_grain_valid"))
        return Judgement(verdict="sufficient" if sufficient else "insufficient", confidence=1,
                         missing_aspects=[], conflicts=[]), {}

    def rewrite(self, question: str, *args: Any) -> tuple[Rewrite, dict[str, int]]:
        """Keep the original question unchanged in oracle replay."""
        return Rewrite(query=question), {}
