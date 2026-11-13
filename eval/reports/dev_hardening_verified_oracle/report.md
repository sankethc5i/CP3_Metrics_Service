# Evaluation report

Split: **dev**. Method: **cached calls or oracle argument replay; zero paid calls**.

Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. Retrieval scores use real retrievers independently of oracle arguments.

Embedding provider: `local`; model: `sentence-transformers/all-MiniLM-L6-v2`.
AS_OF_DATE: `2026-11-01`; seed: `20261101`; k: 6.
New paid calls: 0; spend: $0. Missing configured prices are never replaced with guessed rates.

| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lookup | 0.6963 | 0.8593 | 0.6807 | 1.0000 | 1.0000 | 97.1490 | 319.3069 |
| naive | 0.7889 | 0.7222 | 0.6921 | 1.0000 | 1.0000 | 211.3544 | 312.5364 |
| hybrid | 0.7333 | 0.9000 | 0.7336 | 1.0000 | 1.0000 | 234.5495 | 341.3231 |
| hybrid_rerank | 0.7037 | 0.8444 | 0.6814 | 1.0000 | 1.0000 | 300.2641 | 390.3263 |
| corrective | 0.7037 | 0.8444 | 0.6814 | 1.0000 | 1.0000 | 373.6453 | 592.1827 |

Hybrid beats lookup on Recall@k. Lookup 0.6963; hybrid 0.7333. MRR: 0.8593 vs 0.9000. This is retrieval evidence, not proof of live answer quality. Highest Recall@k in this run: naive.

## Class correctness and attribution

- lookup: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.
- naive: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.
- hybrid: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.
- hybrid_rerank: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.
- corrective: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
  Refusal precision 1.0000; refusal recall 1.0000; unnecessary refusals 0.

## Validator (no SQL executed, zero model calls)

Catch rate: 100.00% on 32 negatives. False-positive rate: 0.00% on 10 benign queries.

Accepted planted negatives: .
These are observed validator limitations. The benchmark does not change the validator to hide them.

## Top failure patterns (per mode)

- lookup: `{}`
- naive: `{}`
- hybrid: `{}`
- hybrid_rerank: `{}`
- corrective: `{}`

## Every failed case

Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.


## Limits

Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. Definition coverage requires an exact catalog definition and a traceable metric ID. Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. No locked test evaluation is included in a dev report.
