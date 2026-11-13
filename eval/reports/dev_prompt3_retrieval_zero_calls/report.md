# Evaluation report

Split: **dev**. Method: **retrieval only; zero LLM**.

Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. Retrieval scores use real retrievers independently of oracle arguments.

Embedding provider: `local`; model: `sentence-transformers/all-MiniLM-L6-v2`.
AS_OF_DATE: `2026-11-01`; seed: `20261101`; k: 6.
New paid calls: 0; spend: $0. Missing configured prices are never replaced with guessed rates.

| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lookup | 1.0000 | 1.0000 | 1.0000 | n/a | n/a | n/a | n/a |

Comparison requires lookup and hybrid on the same dev subset.

## Class correctness and attribution

- lookup: classes `{}`; definition coverage n/a; tokens in/out 0/0; USD/question 0.

## Validator (no SQL executed, zero model calls)

Catch rate: 81.25% on 32 negatives. False-positive rate: 0.00% on 10 benign queries.

Accepted planted negatives: union_nested, star, qualified_star, missing_formula, wrong_formula, literal_formula.
These are observed validator limitations. The benchmark does not change the validator to hide them.

## Top failure patterns (per mode)

- lookup: `{}`

## Every failed case

Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.


## Limits

Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. Definition coverage requires an exact catalog definition and a traceable metric ID. Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. No locked test evaluation is included in a dev report.
