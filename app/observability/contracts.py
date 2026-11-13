"""Shared response contract for future service orchestration."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ServiceResponse(BaseModel):
    """Keep every required field present for every allowed outcome."""

    model_config = ConfigDict(extra="forbid",strict=True)
    outcome: Literal["answer","clarify","refuse","empty_result"]
    value: int | float | str | list[dict[str,Any]] | None
    metric_definition: str | None
    sql: str | None
    trace_id: UUID = Field(default_factory=uuid4)


class PipelineResponse(ServiceResponse):
    """Service contract plus inspectable results, retrieval evidence and trace timeline."""

    text: str = ""
    parameters: dict[str,Any] = Field(default_factory=dict)
    rows: list[dict[str,Any]] = Field(default_factory=list)
    calculations: dict[str,Any] = Field(default_factory=dict)
    retrieved: list[dict[str,Any]] = Field(default_factory=list)
    trace: list[dict[str,Any]] = Field(default_factory=list)
    latency_ms: float = 0.0
    options: list[str] = Field(default_factory=list)
    template: str | None = None
    template_source: Literal["model","deterministic"] | None = None
    crag_path: list[str] = Field(default_factory=list)
    evidence_grades: list[dict[str,Any]] = Field(default_factory=list)
    model_calls: int = 0
    output_token_reservation: int = 0
