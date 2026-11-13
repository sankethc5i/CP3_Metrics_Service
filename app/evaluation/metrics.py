"""Deterministic scoring; no model judgement is used to grade results."""

from collections import Counter
import math
from numbers import Real
from typing import Any

OUTCOMES = ("answer", "clarify", "refuse", "empty_result")


def exact_rows(actual: list[dict[str, Any]], expected: list[dict[str, Any]],
               absolute: float = 1e-6, relative: float = 1e-9) -> bool:
    """Compare complete groups without ordering sensitivity, with numeric tolerance."""
    if len(actual) != len(expected):
        return False
    def key(row: dict[str, Any]) -> str:
        return repr(sorted((k, v) for k, v in row.items() if not isinstance(v, Real)))
    for left, right in zip(sorted(actual, key=key), sorted(expected, key=key)):
        if left.keys() != right.keys():
            return False
        for field in right:
            a, b = left[field], right[field]
            if isinstance(a, Real) and isinstance(b, Real):
                if not math.isfinite(a) or not math.isfinite(b) or not math.isclose(a, b, abs_tol=absolute, rel_tol=relative):
                    return False
            elif a != b:
                return False
    return True


def retrieval_scores(ids: list[str], relevant: set[str], k: int) -> dict[str, float | None]:
    """Compute binary Recall@k, reciprocal first-relevant rank and nDCG@k."""
    if not relevant:
        return {"recall_at_k": None, "mrr": None, "ndcg_at_k": None}
    ranked = list(dict.fromkeys(ids))[:k]
    ranks = [i+1 for i, value in enumerate(ranked) if value in relevant]
    dcg = sum(1/math.log2(rank+1) for rank in ranks)
    ideal = sum(1/math.log2(i+2) for i in range(min(k, len(relevant))))
    return {"recall_at_k": len(ranks)/len(relevant), "mrr": 1/min(ranks) if ranks else 0,
            "ndcg_at_k": dcg/ideal if ideal else 0}


def percentile(values: list[float], q: float) -> float | None:
    """Use linearly interpolated percentiles, including small samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered)-1)*q
    low, high = math.floor(index), math.ceil(index)
    return ordered[low]+(ordered[high]-ordered[low])*(index-low)


def aggregate(rows: list[dict[str, Any]], retrieval_only: bool = False) -> dict[str, Any]:
    """Summarize metrics with explicit denominators and per-class correctness."""
    def mean(field: str) -> float | None:
        values = [r[field] for r in rows if r.get(field) is not None]
        return sum(values)/len(values) if values else None
    answered = [r for r in rows if r["expected_outcome"] == "answer"]
    actual_answers = [r for r in rows if r.get("outcome") == "answer"]
    refused = [r for r in rows if r.get("outcome") == "refuse"]
    expected_refuse = [r for r in rows if r["expected_outcome"] == "refuse"]
    correct_refusals = sum(r.get("outcome") == "refuse" for r in expected_refuse)
    result = {"questions": len(rows), "recall_at_k": mean("recall_at_k"), "mrr": mean("mrr"),
              "ndcg_at_k": mean("ndcg_at_k"), "retrieval_denominator": sum(r.get("mrr") is not None for r in rows),
              "retrieval_p50_ms": percentile([r["retrieval_latency_ms"] for r in rows], .5),
              "retrieval_p95_ms": percentile([r["retrieval_latency_ms"] for r in rows], .95)}
    if retrieval_only:
        return result
    result.update({"outcome_correctness": mean("outcome_ok"),
        "refusal_precision": correct_refusals/len(refused) if refused else None,
        "refusal_recall": correct_refusals/len(expected_refuse) if expected_refuse else None,
        "unnecessary_refusals": sum(r["expected_outcome"] != "refuse" for r in refused),
        "answer_exactness": sum(r.get("answer_exact", False) for r in answered)/len(answered) if answered else None,
        "answer_denominator": len(answered),
        "definition_attribution_coverage": sum(r.get("definition_attributed", False) for r in actual_answers)/len(actual_answers) if actual_answers else None,
        "definition_denominator": len(actual_answers),
        "p50_ms": percentile([r["latency_ms"] for r in rows], .5),
        "p95_ms": percentile([r["latency_ms"] for r in rows], .95),
        "input_tokens": sum(r.get("input_tokens", 0) for r in rows),
        "output_tokens": sum(r.get("output_tokens", 0) for r in rows),
        "cost_usd": sum(r.get("cost_usd", 0) for r in rows),
        "cost_per_question_usd": mean("cost_usd"),
        "per_outcome": {c: {"count": sum(r["expected_outcome"] == c for r in rows),
                            "correct": sum(r["expected_outcome"] == c and r.get("outcome_ok", False) for r in rows)} for c in OUTCOMES},
        "failure_patterns": dict(Counter(r["likely_cause"] for r in rows if r.get("failure")).most_common(5))})
    return result
