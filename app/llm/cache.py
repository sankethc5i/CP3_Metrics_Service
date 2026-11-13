"""Persistent model-call replay and a conservative, shared spending ceiling."""

from dataclasses import asdict, is_dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from app.answers.render import AnswerTemplate
from app.llm.schemas import ToolCall
from app.retrieval.evidence import Judgement, Rewrite
from app.observability.trace import redact


def canonical(value: Any) -> Any:
    """Convert typed call inputs into stable JSON without credentials."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return canonical(asdict(value))
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


class SpendLimit(RuntimeError):
    """A request would exceed the approved evaluation budget."""


class Ledger:
    """Reserve an upper bound before each call; reconcile against reported usage."""

    def __init__(self, prices: dict[str, Any], maximum: Decimal) -> None:
        self.prices, self.maximum, self.spent = prices, maximum, Decimal(0)
        self.calls = 0
        self.exhausted = False

    def cost(self, model: str, usage: dict[str, int]) -> Decimal:
        """Price input and output tokens from configured per-million model prices."""
        price = self.prices[model]
        cached = min(usage.get("provider_cached_input_tokens",0),usage.get("input_tokens",0))
        cached_rate = price.cached_input_per_million if price.cached_input_per_million is not None else price.input_per_million
        return (Decimal(usage.get("input_tokens", 0)-cached)*price.input_per_million
                + Decimal(cached)*cached_rate
                + Decimal(usage.get("output_tokens", 0))*price.output_per_million)/Decimal(1_000_000)

    def reserve(self, model: str, input_bound: int, output_bound: int) -> Decimal:
        """Reject spending before contacting a provider, including on error paths."""
        upper = self.cost(model, {"input_tokens": input_bound, "output_tokens": output_bound})
        if self.exhausted or self.spent+upper > self.maximum:
            self.exhausted = True
            raise SpendLimit("Evaluation stopped at --max-cost; no further paid calls are allowed.")
        self.spent += upper
        self.calls += 1
        return upper


class CachedLanguageModel:
    """Cache every selection, answer, grade and rewrite; never cache oracle results."""

    def __init__(self, settings: Any, delegate: Any = None, oracle: Any = None,
                 ledger: Ledger | None = None) -> None:
        self.settings, self.delegate, self.oracle, self.ledger = settings, delegate, oracle, ledger
        self.sources: list[str] = []

    def set_deadline(self, deadline: float) -> None:
        """Forward request deadlines without changing prompt cache identity."""
        if self.delegate and hasattr(self.delegate, "set_deadline"):
            self.delegate.set_deadline(deadline)

    def embed(self, texts: list[str]) -> Any:
        """Leave vector caching to the provider/model/text-keyed dense cache."""
        if self.delegate is None:
            raise RuntimeError("Offline evaluation requires local embeddings.")
        return self.delegate.embed(texts)

    def _call(self, method: str, *args: Any) -> Any:
        # Include implementation bytes: prompt/schema changes invalidate old outputs.
        from app.config import AS_OF_DATE
        source_files = [Path(__file__).with_name("client.py"), Path(__file__).with_name("schemas.py"),
                        Path(__file__).parents[1]/"answers"/"render.py",
                        Path(__file__).parents[1]/"retrieval"/"evidence.py"]
        client_hash = hashlib.sha256(b"".join(p.read_bytes() for p in source_files)).hexdigest()
        prompt = {"version": 1, "adapter": client_hash, "model": self.settings.model,
                  "method": method, "args": canonical(args), "as_of_date": AS_OF_DATE.isoformat(),
                  "settings": {k: v for k, v in self.settings.model_dump(mode="json").items()
                               if k.endswith("tokens") or k == "max_prompt_bytes"}}
        digest = hashlib.sha256(json.dumps(prompt, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.settings.llm_cache_dir/(digest+".json")
        record = None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if record is not None:
            payload, usage = record["payload"], record["usage"]
            tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                      "cache_hit": 1, "cached_input_tokens": usage.get("input_tokens", 0),
                      "cached_output_tokens": usage.get("output_tokens", 0)}
            self.sources.append("cached")
        else:
            if self.delegate is None:
                if self.oracle is None:
                    raise RuntimeError("No cached call; enable --live to contact the model.")
                self.sources.append("oracle")
                return getattr(self.oracle, method)(*args)
            self.sources.append("live")
            reserve = None
            if self.ledger:
                output = getattr(self.settings, {"select": "select_tokens", "answer": "answer_tokens",
                                                "judge": "grade_tokens", "rewrite": "rewrite_tokens"}[method])
                reserve = self.ledger.reserve(self.settings.model, self.settings.max_prompt_bytes, output)
            value = getattr(self.delegate, method)(*args)
            payload = value.arguments if method == "select" else value[0].model_dump(mode="json")
            tokens = value.tokens if method == "select" else value[1]
            if tokens.get("cache_hit"):
                self.sources[-1] = "cached"
                if self.ledger:
                    self.ledger.calls -= 1
            if self.ledger and reserve is not None:
                # Absent usage is conservatively charged at the reserved ceiling.
                if "input_tokens" in tokens and "output_tokens" in tokens:
                    self.ledger.spent += self.ledger.cost(self.settings.model, tokens)-reserve
            record = {"model": self.settings.model, "prompt_hash": digest, "payload": payload,
                      "usage": tokens, "function": value.name if method == "select" else None}
            self.settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix("."+uuid4().hex+".tmp")
            temporary.write_text(json.dumps(redact(record), ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        if method == "select":
            return ToolCall(record["function"], payload, tokens)
        model = {"answer": AnswerTemplate, "judge": Judgement, "rewrite": Rewrite}[method]
        return model.model_validate(payload), tokens

    def select(self, *args: Any) -> ToolCall:
        """Replay or obtain a governed function call."""
        return self._call("select", *args)

    def answer(self, *args: Any) -> Any:
        """Replay or obtain a structured numeric-reference template."""
        return self._call("answer", *args)

    def judge(self, *args: Any) -> Any:
        """Replay or obtain structured evidence judgement."""
        return self._call("judge", *args)

    def rewrite(self, *args: Any) -> Any:
        """Replay or obtain a bounded rewrite."""
        return self._call("rewrite", *args)
