"""Strict catalog models; SQL is authored governance metadata, never model output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    """Reject misspelled fields instead of silently accepting catalog drift."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Join(StrictModel):
    """A declared many-to-one foreign-key edge in a dimension path."""

    source: str
    target: str
    cardinality: Literal["many_to_one"] = "many_to_one"


class DimensionSource(StrictModel):
    """A dimension column and safe join path for a particular fact table."""

    column: str
    joins: list[Join] = Field(default_factory=list)


class Dimension(StrictModel):
    """Governed dimension, including the time transformation when applicable."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    transform: Literal["identity", "month", "quarter"] = "identity"
    sources: dict[str, DimensionSource]


class Metric(StrictModel):
    """An executable scalar SQL definition and its business-level constraints."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    base_table: str
    grain: str = Field(min_length=1)
    numerator: str | None
    denominator: str | None
    allowed_dimensions: list[str] = Field(min_length=1)
    allowed_time_grains: list[Literal["month", "quarter"]] = Field(min_length=1)
    default_filters: dict[str, str | list[str]]
    synonyms: list[str] = Field(min_length=1)
    unit: Literal["count", "USD", "ratio"]
    business_rules: list[str] = Field(min_length=1)
    example_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_ratio(self) -> "Metric":
        """Require complete ratio components and unique dimension declarations."""
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("Numerator and denominator must be specified together")
        if self.unit == "ratio" and self.numerator is None:
            raise ValueError("Ratio metrics need numerator and denominator")
        if len(set(self.allowed_dimensions)) != len(self.allowed_dimensions):
            raise ValueError("Duplicate allowed dimension")
        return self


class Ambiguity(StrictModel):
    """A term that always requires an explicit choice before metric selection."""

    term: str
    choices: list[str] = Field(min_length=2)
    outcome: Literal["clarify"]
    rule: str = Field(min_length=1)


class Catalog(StrictModel):
    """Versioned catalog containing metrics, dimensions and clarification rules."""

    version: Literal[1]
    as_of_date: str
    currency: Literal["USD"]
    dimensions: list[Dimension] = Field(min_length=6)
    metrics: list[Metric] = Field(min_length=14)
    ambiguities: list[Ambiguity]

    @model_validator(mode="after")
    def check_references(self) -> "Catalog":
        """Reject duplicate IDs and unresolved dimension or ambiguity references."""
        metric_ids = [m.id for m in self.metrics]
        dimension_ids = [d.id for d in self.dimensions]
        if len(set(metric_ids)) != len(metric_ids) or len(set(dimension_ids)) != len(dimension_ids):
            raise ValueError("Duplicate catalog ID")
        for metric in self.metrics:
            if not set(metric.allowed_dimensions) <= set(dimension_ids):
                raise ValueError(f"Unknown dimension in {metric.id}")
            if not set(metric.allowed_time_grains) <= set(metric.allowed_dimensions):
                raise ValueError(f"Time dimensions missing for {metric.id}")
        known = set(metric_ids+dimension_ids)
        for ambiguity in self.ambiguities:
            if not set(ambiguity.choices) <= known:
                raise ValueError("Unknown ambiguity choice")
            for metric in self.metrics:
                if ambiguity.term.casefold() in [s.casefold() for s in metric.synonyms]:
                    raise ValueError("Ambiguous term cannot be an unqualified metric synonym")
        return self
