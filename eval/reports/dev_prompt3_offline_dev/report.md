# Evaluation report

Preliminary diagnostic, superseded by [the verified dev comparison](../dev_prompt3_dev_verified/report.md).
Ambiguity relevance scoring was corrected; reference answers and system behavior were unchanged.

Split: **dev**. Method: **cached calls or oracle argument replay; zero paid calls**.

Oracle replay measures contracts and SQL execution, not natural-language model selection accuracy. Retrieval scores use real retrievers independently of oracle arguments.

Embedding provider: `local`; model: `sentence-transformers/all-MiniLM-L6-v2`.
AS_OF_DATE: `2026-11-01`; seed: `20261101`; k: 6.
New paid calls: 0; spend: $0. Missing configured prices are never replaced with guessed rates.

| Mode | Recall@k | MRR@k | nDCG@k | Outcome accuracy | Answer exactness | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lookup | 0.6870 | 0.8370 | 0.6685 | 1.0000 | 1.0000 | 48.4156 | 120.6531 |
| naive | 0.7889 | 0.7222 | 0.6944 | 1.0000 | 1.0000 | 175.2608 | 304.5078 |
| hybrid | 0.7370 | 0.8822 | 0.7275 | 1.0000 | 1.0000 | 179.9369 | 256.3611 |
| hybrid_rerank | 0.7037 | 0.8278 | 0.6743 | 1.0000 | 1.0000 | 327.5690 | 414.5531 |
| corrective | 0.7037 | 0.8278 | 0.6743 | 0.9091 | 0.8333 | 336.6881 | 654.4852 |

Hybrid beats lookup on Recall@k. Lookup 0.6870; hybrid 0.7370. MRR: 0.8370 vs 0.8822. This is retrieval evidence, not proof of live answer quality.

## Class correctness and attribution

- lookup: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
- naive: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
- hybrid: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
- hybrid_rerank: classes `{"answer": {"count": 30, "correct": 30}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.
- corrective: classes `{"answer": {"count": 30, "correct": 25}, "clarify": {"count": 7, "correct": 7}, "refuse": {"count": 15, "correct": 15}, "empty_result": {"count": 3, "correct": 3}}`; definition coverage 1.0000; tokens in/out 0/0; USD/question 0.0.

## Validator (no SQL executed, zero model calls)

Catch rate: 81.25% on 32 negatives. False-positive rate: 0.00% on 10 benign queries.

Accepted planted negatives: union_nested, star, qualified_star, missing_formula, wrong_formula, literal_formula.
These are observed validator limitations. The benchmark does not change the validator to hide them.

## Top failure patterns (per mode)

- lookup: `{}`
- naive: `{}`
- hybrid: `{}`
- hybrid_rerank: `{}`
- corrective: `{"Conservative catalog evidence matching rejected the requested intent": 5}`

## Every failed case

Full expected/actual rows and step timelines are in failures.jsonl; all timelines are in traces.jsonl.

- `corrective/synonym-01` — Conservative catalog evidence matching rejected the requested intent; trace `97ffb062-d85b-47f3-af8f-addd6ad7ff0b`.
- `corrective/synonym-02` — Conservative catalog evidence matching rejected the requested intent; trace `8b312f7e-7312-4cb7-a5fa-69f42668cd33`.
- `corrective/synonym-03` — Conservative catalog evidence matching rejected the requested intent; trace `7e4d3e64-33ea-4ae5-b431-4701988937ac`.
- `corrective/synonym-05` — Conservative catalog evidence matching rejected the requested intent; trace `dba03c3b-6deb-4611-8e2e-272b5addc610`.
- `corrective/synonym-06` — Conservative catalog evidence matching rejected the requested intent; trace `af23020e-81f4-48e0-9c85-fedd5fb60455`.

## Limits

Warm pipeline latency follows a separately timed retrieval probe; first retrieval may include model startup. Mode order is fixed and scores are cached. Latencies are local measurements, not production SLAs. Definition coverage requires an exact catalog definition and a traceable metric ID. Numeric tolerance: abs 1e-6, rel 1e-9; all expected groups must be present. MRR is truncated at k; undefined intents without approved gold chunks are excluded from retrieval denominators. No locked test evaluation is included in a dev report.
