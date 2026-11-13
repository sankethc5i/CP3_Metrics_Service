"""Budget-free retrieval evaluation plus explicitly oracle-driven contract replay."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import yaml

from app.answers.render import AnswerTemplate, fallback_template
from app.config import ROOT, load_settings
from app.llm.schemas import ToolCall
from app.retrieval.evidence import Judgement, Rewrite, catalog_flags
from app.service import create_service


class ReplayModel:
    """Oracle argument replay: verifies safety contracts, never claims LLM quality."""

    def __init__(self, case: dict[str,Any]) -> None:
        self.case = case

    def select(self, *args: Any) -> ToolCall:
        """Replay authored canonical arguments without spending API tokens."""
        request = self.case["request"]
        return ToolCall("select_metric",request) if request else ToolCall("refuse",{"reason":"Undefined metric."})

    def answer(self, payload: dict[str,Any]) -> tuple[AnswerTemplate,dict[str,int]]:
        """Render a query-sourced scalar or safe row count without model prose."""
        field = next((k for k in payload["result"] if not k.startswith("row")),"row_count")
        return AnswerTemplate(template="Result: {{result."+field+"}}."),{}

    def judge(self, question: str, hits: list, catalog: Any) -> tuple[Judgement,dict[str,int]]:
        """Catalog-check replay, not a live semantic evidence-quality assessment."""
        flags = catalog_flags(question,hits,catalog)
        sufficient = all(flags[k] for k in ("metric_found","dimension_allowed","time_grain_valid"))
        return Judgement(verdict="sufficient" if sufficient else "insufficient",confidence=1.0,
            missing_aspects=[],conflicts=[]),{}

    def rewrite(self, question: str, *args: Any) -> tuple[Rewrite,dict[str,int]]:
        """The smoke replay never fabricates paraphrases or changes the question."""
        return Rewrite(query=question),{}


def main() -> None:
    """Evaluate actual retrieval; label oracle outcome replay separately."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase",choices=["baseline","upgraded"],default="baseline")
    parser.add_argument("--modes",nargs="+",default=["lookup","naive","hybrid"])
    args = parser.parse_args()
    source = ROOT/"eval"/"dev_smoke.yaml"
    cases = yaml.safe_load(source.read_text())["cases"]
    report: dict[str,Any] = {"phase":args.phase,"set_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
        "llm_calls":0,"outcome_method":"oracle argument replay; NOT model-selection accuracy","modes":{}}
    target = ROOT/"eval"/("dev_smoke_"+args.phase+".json")
    if args.phase=="baseline" and target.exists():
        raise SystemExit("Baseline is frozen; choose a new report rather than overwrite it.")
    for mode in args.modes:
        settings = load_settings().model_copy(update={"rag_mode":mode,"trace_dir":ROOT/"data"/"traces"/"dev_smoke"})
        app = create_service(settings)
        if mode in {"hybrid_rerank","corrective"} and settings.rerank_enabled:
            from app.retrieval.rerank import load_cross_encoder
            load_cross_encoder(settings.rerank_model,str(settings.model_cache_dir))
        results = []
        for case in cases:
            started = time.perf_counter()
            try:
                if mode in {"hybrid_rerank","corrective"}:
                    hits = app.retrieval.candidates(case["question"],settings.candidate_k)
                    hits = app.reranker.rerank(case["question"],hits,settings.evidence_k,settings.rerank_timeout) if settings.rerank_enabled else hits[:settings.evidence_k]
                    hits = hits[:settings.top_k]  # comparable recall@6 across all five modes
                else:
                    hits = app.retrieval.search(case["question"],mode,settings.top_k)
                ids = [hit.chunk.metadata.get("metric_id") for hit in hits]
                expected = case["expected_metric_id"]
                rank = ids.index(expected)+1 if expected and expected in ids else None
                app.model = ReplayModel(case)
                response = app.ask(case["question"])
                results.append({"id":case["id"],"expected_metric_id":expected,"rank":rank,
                    "outcome":response.outcome,"outcome_ok":response.outcome==case["expected_outcome"],
                    "latency_ms":(time.perf_counter()-started)*1000})
            except Exception as error:
                results.append({"id":case["id"],"expected_metric_id":case["expected_metric_id"],"error_type":type(error).__name__})
        relevant = [r for r in results if r.get("expected_metric_id")]
        report["modes"][mode] = {"cases":results,"completed":sum("error_type" not in r for r in results),
            "recall_at_k":sum(r.get("rank") is not None for r in relevant)/len(relevant) if relevant else None,
            "mrr":sum(1/r["rank"] for r in relevant if r.get("rank"))/len(relevant) if relevant else None,
            "oracle_outcome_correct":sum(r.get("outcome_ok",False) for r in results)}
        target.write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(mode,json.dumps({k:v for k,v in report["modes"][mode].items() if k!="cases"}),flush=True)


if __name__=="__main__":
    main()
