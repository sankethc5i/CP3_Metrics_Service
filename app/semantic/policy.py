"""Layered metric and literal allow-lists; never interpret arguments as SQL."""

from dataclasses import dataclass
import re

from app.llm.schemas import SelectMetric
from app.semantic.dates import resolve_dates
from app.semantic.models import Catalog, Metric

VALUES: dict[str,tuple[str,...]] = {
    "order_region":("North","South","East","West"),
    "customer_region":("North","South","East","West"),
    "category":("Electronics","Home","Apparel","Sports","Books","Beauty"),
    "brand":("Cedar","Nimbus","Orbit","Maple"),
    "device":("mobile","desktop","tablet"),
    "traffic_source":("organic","paid_search","email","social","direct"),
    "age_group":("18-24","25-34","35-44","45-54","55+"),
    "status":("completed","cancelled","returned","pending"),
}


class PolicyError(ValueError):
    """A known policy failure with an explicit user-facing outcome."""

    def __init__(self, outcome: str, message: str, options: list[str] | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.options = options or []


@dataclass(frozen=True)
class ValidatedRequest:
    """Validated arguments plus the resolved catalog definition and date bounds."""

    arguments: SelectMetric
    metric: Metric
    start: str
    end: str


def metric_exists(request: SelectMetric, catalog: Catalog) -> Metric:
    """Second safety layer: reject IDs absent from the governed catalog."""
    for metric in catalog.metrics:
        if metric.id == request.metric_id:
            return metric
    raise PolicyError("refuse","That metric is not defined in the governed catalog.")


def validate_request(request: SelectMetric, catalog: Catalog) -> ValidatedRequest:
    """Third layer: enforce dimension, filter, value and time-grain allow-lists."""
    metric = metric_exists(request,catalog)
    if len(set(request.dimensions)) != len(request.dimensions):
        raise PolicyError("refuse","Duplicate dimensions are not allowed.")
    if not set(request.dimensions) <= set(metric.allowed_dimensions):
        raise PolicyError("refuse","This metric does not allow the requested dimension.")
    if request.grain != "total" and request.grain not in metric.allowed_time_grains:
        raise PolicyError("refuse","This time grain is not allowed.")
    if set(request.dimensions) & {"month","quarter"}:
        raise PolicyError("clarify","Choose a time grain instead of a time dimension.",["month","quarter","total"])
    for item in request.filters:
        allowed = set(metric.allowed_dimensions)
        if metric.base_table in {"orders","order_items"}:
            allowed.add("status")
        if item.dimension not in allowed:
            raise PolicyError("refuse","This metric does not allow the requested filter.")
        for value in item.values:
            if item.dimension in VALUES:
                if value not in VALUES[item.dimension]:
                    raise PolicyError("clarify","Unknown filter value; choose a governed value.",list(VALUES[item.dimension]))
            elif item.dimension == "month" and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",value):
                continue
            elif item.dimension == "quarter" and re.fullmatch(r"\d{4}-Q[1-4]",value):
                continue
            else:
                raise PolicyError("clarify","Use a calendar month or quarter value.",["YYYY-MM","YYYY-Qn"])
    try:
        start,end = resolve_dates(request.time_range)
    except ValueError as error:
        raise PolicyError("clarify","Supply valid ISO dates with start before end.",["An explicit date range","A relative date range"]) from error
    return ValidatedRequest(request,metric,start,end)


def ambiguity_options(question: str, catalog: Catalog) -> list[str]:
    """Require explicit gross/net revenue and order/customer region qualifiers."""
    text = question.casefold().replace("_"," ")
    options: list[str] = []
    for ambiguity in catalog.ambiguities:
        term = ambiguity.term
        if not re.search(rf"\b{re.escape(term)}\b",text):
            continue
        qualifiers = ("gross","net") if term == "revenue" else ("order","shipping","customer")
        # Qualification must be adjacent, not elsewhere in an unrelated phrase.
        qualified = any(re.search(rf"\b{q}(?:\s+profile)?\s+{term}\b",text) for q in qualifiers)
        if not qualified:
            options.extend(ambiguity.choices)
    return options
