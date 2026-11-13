"""Five-mode dev ablations with explicit oracle labels and paid/locked gates."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from importlib.metadata import version
import json
import platform
from pathlib import Path
import random
import re
import sqlite3
import time
from typing import Any

from app.config import AS_OF_DATE, CATALOG_PATH, ROOT, SEED, Settings, load_settings
from app.evaluation.dataset import load_cases
from app.evaluation.metrics import aggregate, exact_rows, retrieval_scores
from app.evaluation.oracle import OracleModel
from app.evaluation.report import write_reports
from app.evaluation.validator import benchmark_validator
from app.llm.cache import CachedLanguageModel, Ledger
from app.service import create_service

MODES = ("lookup", "naive", "hybrid", "hybrid_rerank", "corrective")


def relevant_chunks(case: dict[str, Any], approved: set[str]) -> set[str]:
    """Gold labels include requested metric, grouping and filter dimensions."""
    gold = {"metric:"+case["expected_metric_id"]} if case["expected_metric_id"] else set()
    dimensions = [*case["dimensions"], *(f["dimension"] for f in case["filters"])]
    if case["grain"] != "total":
        dimensions.append(case["grain"])
    gold.update("dimension:"+d for d in dimensions)
    if case["category"] == "ambiguous":
        if "revenue" in case["question"].lower():
            qualifiers = set(re.findall(r"\b(gross|net)\s+revenue\b", case["question"].lower()))
            gold.update("metric:"+q+"_revenue" for q in (qualifiers or {"gross", "net"}))
        if "units sold" in case["question"].lower():
            gold.add("metric:units_sold")
        if "region" in case["question"].lower():
            gold.update({"dimension:order_region", "dimension:customer_region"})
    return gold & approved


def retrieve(service: Any, question: str, mode: str) -> list[Any]:
    """Probe actual ranked evidence independently of function selection."""
    settings = service.settings
    if mode in {"hybrid_rerank", "corrective"}:
        hits = service.retrieval.candidates(question, settings.candidate_k)
        if settings.rerank_enabled:
            hits = service.reranker.rerank(question, hits, settings.evidence_k, settings.rerank_timeout)
        return hits[:settings.top_k]
    return service.retrieval.search(question, mode, settings.top_k)


def failure_cause(case: dict[str, Any], response: Any, exact: bool) -> str:
    """Assign a reproducible diagnostic hypothesis from observable trace evidence."""
    if any(e.get("error_type") for e in response.trace):
        errors = [e for e in response.trace if e.get("error_type")]
        if any(e["step"] in {"grading", "correction", "final_decision"} for e in errors):
            return "Corrective evidence gate abstained before function selection"
    if response.outcome != case["expected_outcome"]:
        if case["category"] == "invalid_dimension" and response.outcome == "clarify":
            return "Ambiguity/evidence clarification takes precedence over invalid-dimension refusal"
        if case["category"] == "filter_value":
            return "Evidence gate misclassified filter intent before value validation"
        if response.evidence_grades:
            return "Conservative catalog evidence matching rejected the requested intent"
        return "Outcome routing or selection disagrees with the authored policy label"
    if not exact:
        return "Query results or selected metric differ from independent SQL"
    return ""


def evaluate_mode(settings: Settings, cases: list[dict[str, Any]], live: bool, retrieval_only: bool,
                  ledger: Ledger) -> list[dict[str, Any]]:
    """Evaluate one mode; offline cache misses use explicit uncached oracle replay."""
    service = create_service(settings)
    if settings.rag_mode in {"hybrid_rerank","corrective"} and settings.rerank_enabled:
        scorer = getattr(service.reranker,"scorer",None)
        if hasattr(scorer,"warmup"):
            print("Warming configured local reranker before timed questions",flush=True)
            scorer.warmup()
    original = service.model
    delegate = original.delegate if live else None
    approved = {c.id for c in service.retrieval.lookup.chunks}
    rows = []
    for case in cases:
        if ledger.exhausted:
            break
        started = time.perf_counter()
        try:
            hits = retrieve(service, case["question"], settings.rag_mode)
            retrieval_error = None
        except Exception as error:
            hits, retrieval_error = [], type(error).__name__
        elapsed = (time.perf_counter()-started)*1000
        ids = [h.chunk.id for h in hits]
        row = {"id": case["id"], "category": case["category"], "mode": settings.rag_mode,
               "question": case["question"], "expected_outcome": case["expected_outcome"],
               "expected_metric_id": case["expected_metric_id"], "retrieved_ids": ids,
               "retrieval_error": retrieval_error, "retrieval_latency_ms": elapsed,
               **retrieval_scores(ids, relevant_chunks(case, approved), settings.top_k)}
        if not retrieval_only:
            cached = CachedLanguageModel(settings, delegate=delegate,
                                         oracle=None if live else OracleModel(case), ledger=ledger if live else None)
            service.model = cached
            cost_before = ledger.spent
            response = service.ask(case["question"])
            exact = case["expected_outcome"] == "answer" and response.outcome == "answer" and exact_rows(response.rows, case["verified_answer"])
            metric = next((e.get("metric_id") for e in response.trace if e["step"] == "catalog_metric_check"), None)
            definition = next((m.description+" "+" ".join(m.business_rules) for m in service.catalog.metrics if m.id == metric), None)
            usage = {key: sum(e.get("tokens", {}).get(key, 0) for e in response.trace) for key in ("input_tokens", "output_tokens")}
            failure = response.outcome != case["expected_outcome"] or (case["expected_outcome"] == "answer" and not exact)
            row.update(outcome=response.outcome, actual_metric_id=metric,
                       outcome_ok=response.outcome == case["expected_outcome"], answer_exact=exact,
                       actual_rows=response.rows, expected_rows=case["verified_answer"],
                       definition_attributed=bool(metric and definition and response.metric_definition == definition),
                       latency_ms=response.latency_ms, trace_id=str(response.trace_id), trace=response.trace,
                       model_sources=cached.sources, logical_model_calls=response.model_calls,
                       cost_usd=float(ledger.spent-cost_before), failure=failure,
                       likely_cause=failure_cause(case, response, exact) if failure else "", **usage)
        rows.append(row)
        print(f"{settings.rag_mode}: {len(rows)}/{len(cases)} {case['id']}", flush=True)
    return rows


def confirm_live(args: Any, settings: Settings, count: int, modes: int) -> Ledger:
    """Require configured prices, a positive budget and interactive approval first."""
    marker = ROOT/"data"/"eval_state"/"first_live.json"
    if not marker.exists() and (args.limit is None or args.limit > 10 or count > 10):
        raise ValueError("The first live run must explicitly use --limit 10 or fewer.")
    if settings.model not in settings.model_prices:
        raise ValueError("Set MODEL_PRICES_JSON with input_per_million/output_per_million for OPENAI_MODEL before --live.")
    if args.max_cost <= 0:
        raise ValueError("--live requires a positive --max-cost in USD.")
    ledger = Ledger(settings.model_prices, args.max_cost)
    maximum_calls = count*modes*settings.max_llm_calls
    estimate = ledger.cost(settings.model, {"input_tokens": maximum_calls*settings.max_prompt_bytes,
                                            "output_tokens": count*modes*settings.max_output_tokens})
    print(f"LIVE CONFIRMATION: at most {maximum_calls} uncached calls across {count} questions x {modes} modes.", flush=True)
    print(f"Conservative token-budget estimate ${estimate:.6f}; hard spending ceiling ${args.max_cost}. Cache hits cost $0.", flush=True)
    if estimate > args.max_cost:
        raise ValueError("Estimated live cost exceeds --max-cost; no paid calls are allowed. Reduce the question/mode count or token budgets.")
    print("No model prices are assumed. The run stops before a call whose reserved cost exceeds the ceiling.", flush=True)
    if input("Type yes to authorize this live run: ").strip().lower() != "yes":
        raise ValueError("Live run cancelled; no paid calls made.")
    return ledger


def main(argv: list[str] | None = None) -> None:
    """Run reproducible retrieval/validator scoring or gated question-to-answer replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", *MODES), default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-ids", nargs="+", help="Select reviewed IDs from the requested split before --limit")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-locked-test", action="store_true")
    parser.add_argument("--live", action="store_true", help="Default off: cached calls or explicitly labelled oracle arguments")
    parser.add_argument("--max-cost", type=Decimal, default=Decimal(0))
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--validator-only", action="store_true")
    parser.add_argument("--output", type=str)
    parser.add_argument("--report-root", type=Path, help="Optional external directory for generated benchmark payloads")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if not args.max_cost.is_finite() or args.max_cost < 0:
        parser.error("--max-cost must be finite and nonnegative")
    if args.live and (args.retrieval_only or args.validator_only):
        parser.error("Retrieval-only and validator-only always use zero LLM calls; omit --live")
    if args.split == "test":
        if not args.allow_locked_test:
            parser.error("Locked test requires --allow-locked-test; tune on dev only")
        print("WARNING: LOCKED TEST EVALUATION. Report separately; never tune using these results.", flush=True)
    settings = load_settings()
    if settings.embedding_provider != "local" and not args.validator_only and args.mode != "lookup":
        parser.error("Set EMBEDDING_PROVIDER=local for reproducible zero-API retrieval benchmarking.")
    metadata, cases = load_cases(ROOT/"eval"/"questions.yaml", settings.database, args.split, args.allow_locked_test)
    if args.case_ids:
        requested = set(args.case_ids)
        if not requested <= {c["id"] for c in cases}:
            parser.error("--case-ids includes IDs outside the selected split")
        cases = [c for c in cases if c["id"] in requested]
    cases = cases[:args.limit] if args.limit else cases
    random.seed(SEED)
    modes = list(MODES) if args.mode == "all" else [args.mode]
    ledger = confirm_live(args, settings, len(cases), len(modes)) if args.live else Ledger(settings.model_prices, Decimal(0))
    report: dict[str, Any] = {**metadata, "split": args.split,
        "method": "live with persistent cache" if args.live else "retrieval only; zero LLM" if args.retrieval_only else "cached calls or oracle argument replay; zero paid calls",
        "embedding_provider": settings.embedding_provider, "embedding_model": settings.embedding_model,
        "rerank_model": settings.rerank_model, "rerank_enabled": settings.rerank_enabled,
        "model": settings.model, "model_prices": {k: v.model_dump(mode="json") for k, v in settings.model_prices.items()},
        "settings": settings.model_dump(mode="json"), "as_of_date": AS_OF_DATE.isoformat(), "seed": SEED,
        "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                    **{p: version(p) for p in ("sentence-transformers", "torch", "sqlglot", "openai", "matplotlib")}},
        "catalog_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "application_sha256": hashlib.sha256(b"".join(p.read_bytes() for p in sorted((ROOT/"app").rglob("*.py")))).hexdigest(),
        "k": settings.top_k, "category_counts": dict(Counter(c["category"] for c in cases)),
        "outcome_counts": dict(Counter(c["expected_outcome"] for c in cases)),
        "validator": benchmark_validator(ROOT/"eval"/"validator_queries.yaml"), "modes": {},
        "paid_calls": 0, "spent_usd": "0", "comparison": "Comparison requires lookup and hybrid on the same dev subset."}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = (args.report_root or ROOT/"eval"/"reports")/(f"{args.split}_{args.output or stamp}")
    if args.output and (not args.output.replace("_", "").replace("-", "").isalnum()):
        parser.error("--output accepts letters, digits, underscores and hyphens only")
    if directory.exists():
        parser.error("Report directory already exists; choose another --output to preserve prior results")
    try:
        if not args.validator_only:
            for mode in modes:
                if ledger.exhausted:
                    break
                mode_settings = settings.model_copy(update={"rag_mode": mode,
                    "trace_dir": settings.trace_dir/"evaluation"/args.split})
                rows = evaluate_mode(mode_settings, cases, args.live, args.retrieval_only, ledger)
                report["modes"][mode] = {"summary": aggregate(rows, args.retrieval_only), "cases": rows}
    finally:
        report.update(paid_calls=ledger.calls, spent_usd=str(ledger.spent), budget_stopped=ledger.exhausted)
        if args.live and ledger.calls:
            marker = ROOT/"data"/"eval_state"/"first_live.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"limit": args.limit, "calls": ledger.calls}), encoding="utf-8")
        if {"lookup", "hybrid"} <= report["modes"].keys():
            base = report["modes"]["lookup"]["summary"]
            hybrid = report["modes"]["hybrid"]["summary"]
            better = hybrid["recall_at_k"] > base["recall_at_k"]
            report["comparison"] = ("Hybrid beats lookup on Recall@k." if better else "Hybrid does not beat lookup on Recall@k.")+f" Lookup {base['recall_at_k']:.4f}; hybrid {hybrid['recall_at_k']:.4f}. MRR: {base['mrr']:.4f} vs {hybrid['mrr']:.4f}. This is retrieval evidence, not proof of live answer quality."
            best = max(report["modes"], key=lambda m: report["modes"][m]["summary"]["recall_at_k"] or 0)
            report["comparison"] += f" Highest Recall@k in this run: {best}."
        write_reports(report, directory)
    print(f"Report: {directory/'report.md'}", flush=True)


if __name__ == "__main__":
    main()
