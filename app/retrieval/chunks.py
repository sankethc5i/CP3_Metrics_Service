"""Catalog-only chunks; warehouse records never enter the retrieval corpus."""

from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any

from app.semantic.models import Catalog


@dataclass(frozen=True)
class Chunk:
    """One metric, dimension, or distinct business rule with stable metadata."""

    id: str
    kind: str
    text: str
    metadata: dict[str,Any]


@dataclass
class Hit:
    """A retrieved chunk with fusion score and original per-retriever evidence."""

    chunk: Chunk
    score: float
    ranks: dict[str,int] = field(default_factory=dict)
    scores: dict[str,float] = field(default_factory=dict)

    def as_dict(self) -> dict[str,Any]:
        """Return JSON-safe trace/UI data, including chunk metadata and text."""
        return asdict(self)


def chunk_catalog(catalog: Catalog) -> list[Chunk]:
    """Create one chunk per metric, dimension and distinct catalog business rule."""
    chunks: list[Chunk] = []
    rules: dict[str,list[str]] = {}
    for metric in catalog.metrics:
        examples = metric.example_questions or [f"What is {metric.display_name.lower()}?",
            f"Show {metric.display_name.lower()} last month."]
        text = "\n".join([metric.display_name,metric.description,
            "Synonyms: "+", ".join(metric.synonyms),
            "Dimensions: "+", ".join(metric.allowed_dimensions),
            "Examples: "+" ".join(examples),"Rules: "+" ".join(metric.business_rules)])
        chunks.append(Chunk("metric:"+metric.id,"metric",text,{
            "metric_id":metric.id,"aliases":[metric.id.replace("_"," "),metric.display_name,*metric.synonyms],
            "unit":metric.unit,"grain":metric.grain,"examples":examples}))
        for rule in metric.business_rules:
            rules.setdefault(rule,[]).append(metric.id)
    for dimension in catalog.dimensions:
        chunks.append(Chunk("dimension:"+dimension.id,"dimension",dimension.id.replace("_"," ")+"\n"+dimension.description,
            {"dimension_id":dimension.id,"bases":sorted(dimension.sources)}))
    for rule,metric_ids in sorted(rules.items()):
        key = hashlib.sha256(rule.encode()).hexdigest()[:16]
        chunks.append(Chunk("rule:"+key,"rule",rule,{"metric_ids":metric_ids}))
    for ambiguity in catalog.ambiguities:
        chunks.append(Chunk("ambiguity:"+ambiguity.term,"rule",ambiguity.rule,
            {"term":ambiguity.term,"options":ambiguity.choices,"outcome":"clarify"}))
    return chunks
