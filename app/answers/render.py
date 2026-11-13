"""Reject model-authored numeric literals and substitute only known field references."""

import re
from typing import Any

from pydantic import Field
from app.semantic.models import StrictModel

REFERENCE = re.compile(r"\{\{(result|calc)\.([A-Za-z_][A-Za-z0-9_]*)\}\}")
NUMBER_WORDS = re.compile(r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|dozen|half|halves|twice|double|triple)\b",re.I)


class AnswerTemplate(StrictModel):
    """JSON response shape for the separate answer-writing model call."""

    template: str = Field(min_length=1,max_length=12000)


def result_fields(rows: list[dict[str,Any]], metric_id: str) -> dict[str,Any]:
    """Expose row fields as flat names and a scalar metric alias when ungrouped."""
    fields = {f"row{i}_{key}":value for i,row in enumerate(rows) for key,value in row.items()}
    if len(rows) == 1:
        fields[metric_id] = rows[0][metric_id]
    fields["row_count"] = len(rows)
    return fields


def render(template: str, results: dict[str,Any], calculations: dict[str,Any]) -> str:
    """Render only known references; fail closed on raw digits or number words."""
    remainder = REFERENCE.sub("",template)
    if any(character.isnumeric() for character in remainder) or NUMBER_WORDS.search(remainder):
        raise ValueError("Answer template contains a raw number")
    if "{{" in remainder or "}}" in remainder or not REFERENCE.search(template):
        raise ValueError("Malformed or missing field reference")
    def replace(match: re.Match[str]) -> str:
        scope,key = match.groups()
        values = results if scope == "result" else calculations
        if key not in values:
            raise ValueError("Unknown answer field reference")
        value = values[key]
        if value is None:
            return "not available"
        if isinstance(value,float):
            return format(value,".6f").rstrip("0").rstrip(".")
        return str(value)
    return REFERENCE.sub(replace,template)


def fallback_template(rows: list[dict[str,Any]], metric_id: str) -> str:
    """Create a deterministic field-reference answer if model output is invalid."""
    if len(rows)==1:
        return "The result is {{result."+metric_id+"}}."
    return "The query returned {{result.row_count}} groups. See the structured results."
