"""Mock HTTP tool responses exercise the real adapter without network access."""

import json
from pathlib import Path

import httpx
from openai import OpenAI
from pydantic import ValidationError
import pytest

from app.config import Settings
from app.llm.client import OpenAIAdapter
from app.llm.schemas import SelectMetric
from app.semantic.loader import load_catalog
from app.semantic.policy import PolicyError, validate_request
from tests.test_pipeline_safety import arguments


@pytest.mark.parametrize("name,raw", [
    ("execute_sql", '{"sql":"DROP TABLE orders"}'),
    ("select_metric", "not json"), ("select_metric", "[]"), ("select_metric", '"a string"'),
])
def test_untrusted_sdk_function_calls_rejected(name: str, raw: str, warehouse: Path) -> None:
    """Wrong tools and malformed JSON arguments fail before reaching policy or SQL."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert {t["name"] for t in body["tools"]} == {"select_metric", "request_clarification", "refuse"}
        return httpx.Response(200, json={"id": "resp", "object": "response", "created_at": 0,
            "model": "stub", "output": [{"type": "function_call", "name": name, "arguments": raw,
            "call_id": "one", "id": "call"}], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
    with OpenAI(api_key="test-placeholder", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        adapter = OpenAIAdapter(Settings(), client)
        with pytest.raises(ValueError):
            adapter.select("Net revenue", [], load_catalog(database=warehouse))


@pytest.mark.parametrize("count", [0, 2])
def test_exactly_one_tool_call_required(count: int, warehouse: Path) -> None:
    """No tool call and parallel/multiple calls cannot sneak through the adapter."""
    def handler(request: httpx.Request) -> httpx.Response:
        output = [{"type": "function_call", "name": "refuse", "arguments": '{"reason":"Undefined"}',
                   "call_id": str(i), "id": str(i)} for i in range(count)]
        return httpx.Response(200, json={"id": "resp", "object": "response", "created_at": 0,
            "model": "stub", "output": output, "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
    with OpenAI(api_key="test-placeholder", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        with pytest.raises(ValueError, match="exactly one"):
            OpenAIAdapter(Settings(), client).select("Question", [], load_catalog(database=warehouse))


@pytest.mark.parametrize("metric,dimension", [("orders", "category"), ("conversion_rate", "brand"),
    ("new_customers", "device"), ("net_revenue", "city"), ("net_revenue", "month")])
def test_disallowed_selection_combinations(metric: str, dimension: str, warehouse: Path) -> None:
    """A valid metric ID never authorizes an unapproved dimension combination."""
    with pytest.raises(PolicyError):
        validate_request(arguments(metric, dimensions=[dimension]), load_catalog(database=warehouse))


@pytest.mark.parametrize("grain", ["day", "week", "year", "month; DROP TABLE orders"])
def test_disallowed_grains_fail_schema(grain: str) -> None:
    """Only the three exposed grain choices can reach catalog policy validation."""
    with pytest.raises(ValidationError):
        SelectMetric.model_validate({**arguments().model_dump(), "grain": grain})
