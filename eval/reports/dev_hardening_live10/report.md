# Evaluation report

Split: **dev**. Method: **live with persistent cache**.

Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. Retrieval scores use real retrievers independently of oracle arguments.

Embedding provider: `local`; model: `sentence-transformers/all-MiniLM-L6-v2`.
AS_OF_DATE: `2026-11-01`; seed: `20261101`; k: 6.
New paid calls: 20; spend: $0.0051802. Missing configured prices are never replaced with guessed rates.

| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| corrective | 0.5926 | 0.5185 | 0.4612 | 0.6000 | 0.5000 | 8504.6221 | 12308.0378 |

Comparison requires lookup and hybrid on the same dev subset.

## Class correctness and attribution

- corrective: classes `{"answer": {"count": 6, "correct": 3}, "clarify": {"count": 1, "correct": 1}, "refuse": {"count": 2, "correct": 2}, "empty_result": {"count": 1, "correct": 0}}`; definition coverage 1.0000; tokens in/out 34727/3415; USD/question 0.00051802.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.

## Validator (no SQL executed, zero model calls)

Catch rate: 100.00% on 32 negatives. False-positive rate: 0.00% on 10 benign queries.

Accepted planted negatives: .
These are observed validator limitations. The benchmark does not change the validator to hide them.

## Top failure patterns (per mode)

- corrective: `{"Conservative catalog evidence matching rejected the requested intent": 3, "Evidence gate misclassified filter intent before value validation": 1}`

## Every failed case

Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.

- `corrective/synonym-03` — Conservative catalog evidence matching rejected the requested intent; trace `9682ea24-b2a7-4778-9af9-87457e42f06b`.
- `corrective/synonym-05` — Conservative catalog evidence matching rejected the requested intent; trace `25676f76-b08c-4179-b6eb-0ffb11f7e0ba`.
- `corrective/synonym-06` — Conservative catalog evidence matching rejected the requested intent; trace `04fabc51-55a8-411b-86b5-9423301af679`.
- `corrective/filter_value-06` — Evidence gate misclassified filter intent before value validation; trace `d8ec66f8-42fb-4db4-9c0b-9a4b5215de47`.

## Limits

Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. Definition coverage requires an exact catalog definition and a traceable metric ID. Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. No locked test evaluation is included in a dev report.
