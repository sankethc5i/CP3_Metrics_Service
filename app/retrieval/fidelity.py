"""Conservative retrieval-query expansion checks that preserve original intent."""

from collections import Counter
import re

from app.retrieval.evidence import matching_metrics, requested_dimensions
from app.semantic.models import Catalog


def faithful_rewrite(original: str, rewritten: str, catalog: Catalog) -> bool:
    """Require the original verbatim prefix and allow only its governed metric synonyms."""
    if not rewritten.startswith(original) or len(rewritten)>4500:
        return False
    suffix = rewritten[len(original):]
    if re.search(r"[^A-Za-z\s,]",suffix):
        return False
    ids = matching_metrics(original,catalog)
    allowed = {word for metric in catalog.metrics if metric.id in ids for alias in metric.synonyms
        for word in re.findall(r"[a-z]+",alias.casefold())}
    if not set(re.findall(r"[a-z]+",suffix.casefold()))<=allowed:
        return False
    # Preserve numeric/date/currency/unit and negation occurrences exactly.
    protected = r"\d+(?:[./:-]\d+)*|[%$€£]|\b(?:not|no|never|without|excluding|except|usd|eur|dollars|units|percent|orders)\b"
    if Counter(re.findall(protected,original.casefold()))!=Counter(re.findall(protected,rewritten.casefold())):
        return False
    return set(matching_metrics(rewritten,catalog))<=set(ids) and requested_dimensions(original,catalog)==requested_dimensions(rewritten,catalog)
