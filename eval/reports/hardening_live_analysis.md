# Approved live dev diagnostic

The single approved run completed all ten reviewed dev questions in corrective
mode. It included the five original unfamiliar paraphrases, plus ordinary
answer, ambiguous, unsupported metric, invalid dimension and valid-empty cases.
No locked questions were loaded for evaluation. No second paid run was made.

| Measurement | Live | Oracle, identical ten IDs |
|---|---:|---:|
| Outcome correctness | 6/10 (60%) | 10/10 (100%) |
| Answer exactness, expected-answer denominator | 3/6 (50%) | 6/6 (100%) |
| Incorrect numeric answers returned | 0 | 0 |
| Refusal precision | 2/2 (100%) | 2/2 (100%) |
| Refusal recall | 2/2 (100%) | 2/2 (100%) |
| Unnecessary refusals | 0 | 0 |

All four live disagreements were **clarifications**, not incorrect financial
values or unsafe execution. The run answered the ordinary net-revenue question
and two paraphrases, clarified the other three paraphrases, and clarified the
valid-empty case. These figures describe a small diagnostic sample,
not general model accuracy.

| Case | Expected | Actual | Evidence from the trace |
|---|---|---|---|
| synonym-03 | answer | clarify | Tool resolution selected order_lines correctly; correction retained its definition. The semantic grader still considered entries vs units vs receipts ambiguous. |
| synonym-05 | answer | clarify | Tool resolution selected conversion_rate correctly. The grader interpreted “eventually” as an unspecified later-purchase attribution window; the bounded rewrite did not resolve that concern. |
| synonym-06 | answer | clarify | Tool resolution selected net_revenue correctly. The grader asked for a time period even though the application has an all-time default. |
| filter_value-06 | empty_result | clarify | The grader asked for the event date used by net revenue/refunds before execution; the compiler's governed date column was not explicit in its retrieved prose. |

The five original paraphrases now **answer or clarify** in the real run, with
zero over-refusals. The full dev oracle rerun answers all five. Live semantic
grading is still more conservative than the authored labels. Supplying explicit
governed date/default/attribution metadata to the grader is a remaining
improvement; it should be tested without overriding valid ambiguous verdicts.
The current safety checks were not relaxed to make live scores look better.

Preflight estimate: at most 40 uncached calls and USD 0.126. Approved hard cap:
USD 0.15. Actual: **20 paid attempts, 34,727 input tokens, 3,415 output tokens,
USD 0.0051802**, computed by the ledger using the supplied model prices.
Budget stop: false. No partial-report truncation was needed. Existing disk/API
response caching remains enabled for future replay.

Full report, per-question CSV and all failure traces:
[dev_hardening_live10/report.md](dev_hardening_live10/report.md).
Matched comparison: [hardening_before_after.md](hardening_before_after.md).
