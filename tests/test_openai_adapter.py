"""Exercise real SDK serialization and response parsing through mocked HTTP."""

import json
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from app.config import Settings
from app.llm.client import OpenAIAdapter, function_tools
from app.retrieval.chunks import chunk_catalog
from app.semantic.loader import load_catalog
from tests.test_pipeline_safety import arguments


def test_only_three_strict_function_schemas() -> None:
    """No SQL tool or other function is exposed; nested objects remain closed."""
    tools = function_tools()
    assert {t["function"]["name"] for t in tools} == {"select_metric","request_clarification","refuse"}
    for tool in tools:
        function = tool["function"]
        assert function["strict"] is True
        assert function["parameters"]["additionalProperties"] is False
        assert set(function["parameters"]["required"]) == set(function["parameters"]["properties"])


def test_sdk_select_answer_embeddings(warehouse: Path) -> None:
    """The actual pinned SDK sends strict tools and structured JSON formats."""
    requests: list[dict[str,Any]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200,json={"object":"list","model":"embedding-test",
                "data":[{"object":"embedding","index":0,"embedding":[0.5,0.8]}],
                "usage":{"prompt_tokens":3,"total_tokens":3}})
        if "tools" in body:
            output = [{"id":"fc_test","call_id":"call_test","type":"function_call",
                "name":"select_metric","arguments":json.dumps(arguments().model_dump()),"status":"completed"}]
        else:
            name = body["text"]["format"]["name"]
            result = {"template":"Net revenue is {{result.net_revenue}}."}
            if name=="Judgement":
                result = {"verdict":"sufficient","confidence":0.9,"missing_aspects":[],"conflicts":[]}
            elif name=="Rewrite":
                result = {"query":"Show net revenue. net sales"}
            output = [{"id":"msg_test","type":"message","role":"assistant","status":"completed",
                "content":[{"type":"output_text","text":json.dumps(result),"annotations":[]}]}]
        assert request.url.path.endswith("responses")
        return httpx.Response(200,json={"id":"resp_test","object":"response","created_at":0,
            "model":"test-model","status":"completed","output":output,
            "usage":{"input_tokens":20,"output_tokens":10,"total_tokens":30}})
    client = OpenAI(api_key="test-placeholder",http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter = OpenAIAdapter(Settings(embedding_provider="openai"),client)
    catalog = load_catalog(database=warehouse)
    call = adapter.select("What is net revenue?",[],catalog)
    assert call.name=="select_metric" and call.tokens["total_tokens"]==30
    assert len(requests[0]["tools"])==3 and requests[0]["tool_choice"]=="required"
    assert "SELECT " not in json.dumps(requests[0]["input"])
    template,tokens = adapter.answer({"result":{"net_revenue":42},"calc":{}})
    assert "{{result.net_revenue}}" in template.template
    assert requests[1]["text"]["format"]["strict"] is True
    assert adapter.embed(["catalog definition"]).vectors==[[0.5,0.8]]
    judgement,_ = adapter.judge("Show net revenue.",[],catalog)
    assert judgement.verdict=="sufficient"
    properties = requests[-1]["text"]["format"]["schema"]["properties"]
    assert set(properties)=={"verdict","confidence","missing_aspects","conflicts"}
    rewrite,_ = adapter.rewrite("Show net revenue.",[],catalog)
    assert rewrite.query.startswith("Show net revenue.")
    client.close()
