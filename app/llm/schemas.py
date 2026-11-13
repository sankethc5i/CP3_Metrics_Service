"""The only three exposed function-call schemas and raw-call transport."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, model_validator

from app.semantic.models import StrictModel


class Filter(StrictModel):
    """An equality or membership predicate on a governed dimension or status."""

    dimension: str = Field(min_length=1,max_length=80)
    operator: Literal["eq", "in"]
    values: list[str] = Field(min_length=1,max_length=30)

    @model_validator(mode="after")
    def check_arity(self) -> "Filter":
        """Equality accepts exactly one literal value."""
        if self.operator == "eq" and len(self.values) != 1:
            raise ValueError("eq requires one value")
        return self


class TimeRange(StrictModel):
    """Explicit ISO bounds or a deterministic relative-period name."""

    start: str | None
    end: str | None
    relative: Literal["all_time","this_month","last_month","this_quarter","last_quarter","this_year","last_year","last_30_days"] | None

    @model_validator(mode="after")
    def check_choice(self) -> "TimeRange":
        """Prevent mixed or partial relative and absolute date specifications."""
        if self.relative is not None:
            if self.start is not None or self.end is not None:
                raise ValueError("Relative periods cannot carry explicit dates")
        elif self.start is None or self.end is None:
            raise ValueError("Both explicit dates are required")
        return self


class SelectMetric(StrictModel):
    """Select one catalog metric, safe dimensions and parameterized constraints."""

    metric_id: str = Field(min_length=1,max_length=80)
    dimensions: list[str] = Field(max_length=4)
    filters: list[Filter] = Field(max_length=8)
    time_range: TimeRange
    grain: Literal["total","month","quarter"]


class RequestClarification(StrictModel):
    """Offer concrete choices when the question cannot identify one governed request."""

    options: list[str] = Field(min_length=2,max_length=8)


class Refuse(StrictModel):
    """Reject an undefined metric or unsupported operation."""

    reason: str = Field(min_length=1,max_length=500)


FUNCTION_MODELS = {"select_metric":SelectMetric,"request_clarification":RequestClarification,"refuse":Refuse}


@dataclass
class ToolCall:
    """Untrusted model output; arguments are validated later in the safety chain."""

    name: str
    arguments: dict[str, Any]
    tokens: dict[str,int] = field(default_factory=dict)
