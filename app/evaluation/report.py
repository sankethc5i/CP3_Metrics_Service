"""Portable CSV, Markdown, trace and headless matplotlib benchmark artifacts."""

import csv
import json
from pathlib import Path
from typing import Any


def write_reports(report: dict[str, Any], directory: Path) -> None:
    """Persist summaries and every failure, keeping locked reports separately named."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory/"results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = [row for result in report["modes"].values() for row in result["cases"]]
    if rows:
        excluded = {"trace", "actual_rows", "expected_rows", "retrieved_ids"}
        fields = sorted({k for row in rows for k in row if k not in excluded})
        with (directory/"questions.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items() if k not in excluded})
    summaries = [{"mode": mode, **data["summary"]} for mode, data in report["modes"].items()]
    if summaries:
        with (directory/"summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
    failures = [r for r in rows if r.get("failure")]
    with (directory/"failures.jsonl").open("w", encoding="utf-8") as stream:
        for row in failures:
            stream.write(json.dumps(row)+"\n")
    with (directory/"traces.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps({k: row.get(k) for k in ("id", "mode", "trace_id", "trace")})+"\n")
    lines = ["# Evaluation report", "", f"Split: **{report['split']}**. Method: **{report['method']}**.", "",
        "Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. "
        "Retrieval scores use real retrievers independently of oracle arguments.", "",
        f"Embedding provider: `{report['embedding_provider']}`; model: `{report['embedding_model']}`.",
        f"AS_OF_DATE: `{report['as_of_date']}`; seed: `{report['seed']}`; k: {report['k']}.",
        f"New paid calls: {report['paid_calls']}; spend: ${report['spent_usd']}. "
        "Missing configured prices are never replaced with guessed rates.", "",
        "| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value: Any) -> str:
        return "n/a" if value is None else f"{value:.4f}"
    for item in summaries:
        lines.append("| "+" | ".join([item["mode"], *[fmt(item.get(k)) for k in (
            "recall_at_k", "mrr", "ndcg_at_k", "outcome_correctness", "answer_exactness", "p50_ms", "p95_ms")]])+" |")
    lines += ["", report["comparison"], "", "## Class correctness and attribution", ""]
    for mode, data in report["modes"].items():
        summary = data["summary"]
        lines += [f"- {mode}: classes `{json.dumps(summary.get('per_outcome', {}))}`; "
                  f"definition coverage {fmt(summary.get('definition_attribution_coverage'))}; "
                  f"tokens in/out {summary.get('input_tokens', 0)}/{summary.get('output_tokens', 0)}; "
                  f"USD/question {summary.get('cost_per_question_usd', 0)}."]
        if "refusal_precision" in summary:
            lines.append(f"  Refusal precision {fmt(summary['refusal_precision'])}; refusal recall "
                         f"{fmt(summary['refusal_recall'])}; unnecessary refusals {summary['unnecessary_refusals']}.")
    validator = report.get("validator")
    if validator:
        lines += ["", "## Validator (no SQL executed, zero model calls)", "",
                  f"Catch rate: {validator['catch_rate']:.2%} on {validator['bad_count']} negatives. "
                  f"False-positive rate: {validator['false_positive_rate']:.2%} on {validator['benign_count']} benign queries.", "",
                  "Accepted planted negatives: "+", ".join(r["id"] for r in validator["cases"] if r["kind"] == "bad" and not r["rejected"])+".",
                  "These are observed validator limitations. The benchmark does not change the validator to hide them."]
    lines += ["", "## Top failure patterns (per mode)", ""]
    for mode, data in report["modes"].items():
        lines.append(f"- {mode}: `{json.dumps(data['summary'].get('failure_patterns', {}))}`")
    lines += ["", "## Every failed case", "", "Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.", ""]
    lines.extend(f"- `{r['mode']}/{r['id']}` — {r['likely_cause']}; trace `{r.get('trace_id')}`." for r in failures)
    lines += ["", "## Limits", "", "Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. "
              "Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. "
              "Definition coverage requires an exact catalog definition and a traceable metric ID. "
              "Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. "
              "MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. "
              "No locked test evaluation is included in a dev report."]
    (directory/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    if summaries:
        draw_charts(summaries, directory)


def draw_charts(summaries: list[dict[str, Any]], directory: Path) -> None:
    """Export readable comparison charts using matplotlib's noninteractive backend."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    modes = [r["mode"] for r in summaries]
    for axis, (field, title) in zip(axes.flat, [
        ("recall_at_k", "Retrieval Recall@k"), ("mrr", "Retrieval MRR@k"),
        ("outcome_correctness", "Outcome accuracy (check report method)"), ("p95_ms", "Warm pipeline p95 latency (ms)")]):
        values = [r.get(field) for r in summaries]
        axis.bar(modes, [v or 0 for v in values], color="#347fa3")
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=25)
        if field != "p95_ms":
            axis.set_ylim(0, 1.08)
        for i, value in enumerate(values):
            if value is None:
                axis.text(i, 0, "n/a", ha="center")
        axis.grid(axis="y", alpha=.2)
    figure.savefig(directory/"comparison.png", dpi=150)
    figure.savefig(directory/"comparison.svg")
    plt.close(figure)
