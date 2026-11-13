# Evaluation report

Split: **test**. Method: **cached calls or oracle argument replay; zero paid calls**.

Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. Retrieval scores use real retrievers independently of oracle arguments.

Embedding provider: `local`; model: `sentence-transformers/all-MiniLM-L6-v2`.
AS_OF_DATE: `2026-11-01`; seed: `20261101`; k: 6.
New paid calls: 0; spend: $0. Missing configured prices are never replaced with guessed rates.

| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| corrective | 0.8148 | 0.9074 | 0.7926 | 0.9545 | 1.0000 | 354.0338 | 532.6245 |

Comparison requires lookup and hybrid on the same dev subset.

## Class correctness and attribution

- corrective: classes `{"answer": {"count": 12, "correct": 12}, "clarify": {"count": 3, "correct": 3}, "refuse": {"count": 6, "correct": 5}, "empty_result": {"count": 1, "correct": 1}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 0.8333; unnecessary refusals 0.

## Validator (no SQL executed, zero model calls)

Catch rate: 100.00% on 32 negatives. False-positive rate: 0.00% on 10 benign queries.

Accepted planted negatives: .
These are observed validator limitations. The benchmark does not change the validator to hide them.

## Top failure patterns (per mode)

- corrective: `{"Ambiguity/evidence clarification takes precedence over invalid-dimension refusal": 1}`

## Every failed case

Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.

- `corrective/invalid_dimension-07` — Ambiguity/evidence clarification takes precedence over invalid-dimension refusal; trace `83c5cc15-20eb-419e-a6ea-faec88cc19aa`.

## Limits

Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. Definition coverage requires an exact catalog definition and a traceable metric ID. Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. No locked test evaluation is included in a dev report.
