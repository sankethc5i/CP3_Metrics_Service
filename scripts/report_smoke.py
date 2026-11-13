"""Generate an honest comparison from frozen baseline and upgraded report artifacts."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT


def main() -> None:
    """Compare retrieval ranks; explicitly distinguish oracle replay from model accuracy."""
    baseline = json.loads((ROOT/"eval"/"dev_smoke_baseline.json").read_text())
    upgraded = json.loads((ROOT/"eval"/"dev_smoke_upgraded.json").read_text())
    digest = hashlib.sha256((ROOT/"eval"/"dev_smoke.yaml").read_bytes()).hexdigest()
    if baseline["set_sha256"]!=digest or upgraded["set_sha256"]!=digest:
        raise SystemExit("Reports do not describe the same smoke set")
    rows = []
    for mode,result in upgraded["modes"].items():
        previous = baseline["modes"].get(mode)
        prior = f"{previous['recall_at_k']:.4f} / {previous['mrr']:.4f}" if previous else "new mode"
        rows.append(f"| {mode} | {prior} | {result['recall_at_k']:.4f} | {result['mrr']:.4f} | {result['oracle_outcome_correct']}/{len(result['cases'])} |")
    sample = next(iter(upgraded["modes"].values()))["cases"]
    count = len(sample)
    labeled = sum(bool(case.get("expected_metric_id")) for case in sample)
    content = f"""# Temporary development smoke comparison

The pre-upgrade Prompt 2 baseline was run and frozen before integrating reranking
or correction. It is stored in eval/dev_smoke_baseline.json; the upgraded report
is eval/dev_smoke_upgraded.json. Both use the same SHA-256-verified smoke set.

There are {count} questions covering answer, clarify, refuse and empty_result.
Retrieval scores use the {labeled} metric-labeled cases; expected_metric_id is null
for deliberately ambiguous/undefined metrics. Reciprocal rank is truncated at
the same six returned positions for every mode. New modes actually retrieve 25
and rerank to ten before this comparable top-six measurement.

| Mode | Baseline recall@6 / MRR@6 | Upgraded recall@6 | Upgraded MRR@6 | Oracle outcome replay |
|---|---|---:|---:|---:|
"""+"\n".join(rows)+f"""

Comparison OpenAI calls: baseline {baseline['llm_calls']}, upgraded {upgraded['llm_calls']}.
Dense retrieval used real local all-MiniLM-L6-v2 embeddings; new modes used the
real local ms-marco-MiniLM-L6-v2 cross-encoder. Pair and embedding caches were
reused. The reports are reproducible development diagnostics, not locked tests.

**No improvement over hybrid is established.** The added cross-encoder retains
recall but worsens reciprocal rank on this small set. The original hybrid remains
default; no prompt, threshold or model-weight tuning was performed to manufacture
a win. More varied future dev cases are needed before claiming a benefit.

Oracle outcome replay supplies authored canonical arguments to the real safety,
SQL and read-only execution pipeline. Corrective judgement replay uses catalog
checks. Neither is a live LLM selection/grading measurement. Outcome agreement
therefore MUST NOT be described as end-to-end model accuracy. Retrieval scores
also do not measure answer faithfulness or grader calibration.

Timing fields are diagnostic: model warmup, cache state and file I/O differ. They
are not a controlled latency benchmark. A budget-limited live schema check, if
performed, is separate from these zero-call comparison runs.

Run from the repository root:

```powershell
.\\.venv\\Scripts\\python.exe scripts/evaluate_smoke.py --phase upgraded --modes lookup naive hybrid hybrid_rerank corrective
.\\.venv\\Scripts\\python.exe scripts/report_smoke.py
```

The baseline command refuses to overwrite its frozen artifact. The temporary
smoke set must never be copied to the locked split; the full dev set is future
work and locked evaluation remains untouched.
"""
    (ROOT/"docs"/"04-dev-smoke-comparison.md").write_text(content,encoding="utf-8")
    print("\n".join(rows))


if __name__=="__main__":
    main()
