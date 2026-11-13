"""Structured evidence judgements with catalog-derived booleans and actions."""

import re
from typing import Literal

from pydantic import Field

from app.retrieval.chunks import Hit
from app.semantic.models import Catalog, StrictModel
from app.semantic.policy import ambiguity_options


class Judgement(StrictModel):
    """Only semantic judgement fields are supplied by the model."""

    verdict: Literal["sufficient","ambiguous","conflicting","insufficient"]
    confidence: float = Field(ge=0,le=1)
    missing_aspects: list[str]
    conflicts: list[str]


class EvidenceGrade(Judgement):
    """Final grade: flags and routing are computed locally, never trusted to an LLM."""

    metric_found: bool
    dimension_allowed: bool
    time_grain_valid: bool
    metric_id: str | None
    next_action: Literal["proceed","rewrite","clarify","correct","abstain"]


class Rewrite(StrictModel):
    """A retrieval-only conservative query expansion; not a new user instruction."""

    query: str = Field(min_length=1,max_length=4500)


def matching_metrics(question: str, catalog: Catalog) -> list[str]:
    """Resolve explicit metric names/synonyms without interpreting data or formulas."""
    text = " "+" ".join(re.findall(r"[a-z0-9]+",question.casefold()))+" "
    matches = []
    for metric in catalog.metrics:
        aliases = [metric.id.replace("_"," "),metric.display_name,*metric.synonyms]
        lengths = []
        for alias in aliases:
            alias = alias.casefold()
            if " "+alias+" " not in text:
                continue
            # A single-word metric mentioned as an adjustment ("after refunds")
            # does not establish the requested metric. Resolve that intent through
            # governed tool selection rather than treating the operand as the goal.
            mentions = list(re.finditer(r"\b"+re.escape(alias)+r"\b",text))
            operand = len(alias.split())==1 and all(re.search(
                r"\b(?:after|before|excluding|without|minus|less)\b(?:\s+[a-z]+){0,4}\s+$",
                text[:match.start()]) for match in mentions)
            if not operand:
                lengths.append(len(alias.split()))
        length = max(lengths or [0])
        if length:
            matches.append((metric.id,length))
    maximum = max((length for _,length in matches),default=0)
    return [name for name,length in matches if length==maximum]


def requested_dimensions(question: str, catalog: Catalog) -> set[str]:
    """Extract governed dimension terms and explicit unknown by-dimensions conservatively."""
    text = question.casefold().replace("_"," ")
    result = {d.id for d in catalog.dimensions if re.search(r"\b"+re.escape(d.id.replace("_"," "))+r"\b",text)}
    if "device type" in text:
        result.add("device")
    names = [d.id.replace("_"," ") for d in catalog.dimensions]+["device type"]
    for clause in re.findall(r"\bby\s+([^?.;]+)",text):
        for part in re.split(r"\s+and\s+|,",clause):
            part = part.strip()
            if part and not any(re.match(re.escape(name)+r"\b",part) for name in names):
                result.add("unsupported:"+part.split()[0])
    return result


def catalog_flags(question: str, hits: list[Hit], catalog: Catalog, resolved_metric_id: str | None = None) -> dict[str,bool | str | None]:
    """Check exact catalog IDs, supported dimensions and time grains independently."""
    matches = matching_metrics(question,catalog)
    if not matches and resolved_metric_id is not None:
        matches = [resolved_metric_id]
    metric = next((m for m in catalog.metrics if len(matches)==1 and m.id==matches[0]),None)
    found = metric is not None and any(h.chunk.metadata.get("metric_id")==metric.id for h in hits)
    dimensions = requested_dimensions(question,catalog)
    grains = set(re.findall(r"\b(month|quarter)\b",question.casefold()))
    unsupported = bool(re.search(r"\b(daily|weekly|hourly|yearly)\b|\b(?:by|per|each|every)\s+(?:day|week|hour|year)\b",question.casefold()))
    return {"metric_found":found,"dimension_allowed":bool(metric and dimensions<=set(metric.allowed_dimensions)),
        "time_grain_valid":bool(metric and not unsupported and grains<=set(metric.allowed_time_grains)),
        "metric_id":metric.id if metric else None}


def combine_grade(question: str, hits: list[Hit], catalog: Catalog, judgement: Judgement, threshold: float,
                  resolved_metric_id: str | None = None) -> EvidenceGrade:
    """Override semantic optimism with local ambiguity rules and catalog constraints."""
    flags = catalog_flags(question,hits,catalog,resolved_metric_id)
    verdict = judgement.verdict
    missing = list(judgement.missing_aspects)
    conflicts = list(judgement.conflicts)
    if ambiguity_options(question,catalog) or len(matching_metrics(question,catalog))>1:
        verdict = "conflicting"
        conflicts = conflicts or ambiguity_options(question,catalog) or matching_metrics(question,catalog)
    elif verdict not in {"ambiguous","conflicting"}:
        if not all(flags[name] for name in ("metric_found","dimension_allowed","time_grain_valid")) or judgement.confidence<threshold:
            verdict = "insufficient"
            missing += [name for name in ("metric_found","dimension_allowed","time_grain_valid") if not flags[name]]
    action = {"sufficient":"proceed","ambiguous":"rewrite","conflicting":"clarify","insufficient":"correct"}[verdict]
    return EvidenceGrade(verdict=verdict,confidence=judgement.confidence,missing_aspects=missing,
        conflicts=conflicts,next_action=action,**flags)
