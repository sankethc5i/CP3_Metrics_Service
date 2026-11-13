# Hardening tests and defects

All correctness measurements use dev questions. Locked questions and their
reference answers were not used for tuning or system evaluation in this phase.
Original questions, reference SQL and the 32 planted negatives remain intact.

## Test plan and reproduction

The suite covers lookup/BM25 exact names, synonyms, partial typos and honest
full-typo misses; controlled dense vectors; stable ties, missing lists and
duplicate RRF hits. Stub vectors establish algorithm behavior, not real model
semantic accuracy. Actual retrieval quality is measured separately in dev runs.

Mocked HTTP responses exercise the real OpenAI adapter: exactly one of three
tools, malformed JSON, non-object arguments and forbidden tools. Pipeline tests
cover unknown IDs, refusal, clarification, invalid dimensions and grains,
malicious argument literals, every security layer, and no execution after a
failed validation. The compiler matrix covers every metric, each permitted
single non-time dimension or no dimension, and total/month/quarter grains.
Time dimensions are represented by the grain field, as required by the schema.
Independent handwritten SQL checks dev examples and raw order-grain revenue;
grouped totals and distinct order/line counts expose fan-out.

Date checks include frozen last month, previous quarter, YTD, year rollover,
leap February, half-open boundaries and invalid ranges. Answer tests cover
calculator-sourced percentages, unresolved/invented references and deterministic
rendering fallback. Integration checks verify trace order, tokens, latency and
credential redaction. Failure tests inject timeouts, rate limits and database
errors. CLI tests exercise real CSV/Markdown/PNG/SVG/JSONL exports and locked,
budget and contradictory-flag gates without network calls.

New pinned test packages: `pytest-cov==7.0.0`, `coverage==7.13.4`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --cov=app --cov=ui --cov-report=term-missing --cov-report=json:eval/reports/hardening_coverage/coverage.json --cov-report=html:eval/reports/hardening_coverage/html --cov-report=xml:eval/reports/hardening_coverage/coverage.xml
.\.venv\Scripts\python.exe scripts/evaluate.py --mode all
.\.venv\Scripts\python.exe scripts/compare_hardening.py
```

Coverage includes backend, evaluation code and UI, with branches enabled; no
production modules are excluded to inflate coverage. Generated HTML/XML/JSON
reports are under `eval/reports/hardening_coverage/`.

## Defects fixed

| Defect | Fix | Regression evidence |
|---|---|---|
| Nested UNION accepted | Reject UNION/INTERSECT/EXCEPT anywhere in the AST | Original nested-union probe and new nested set-operation tests |
| Raw and qualified star projections accepted | Reject row stars everywhere; retain COUNT(*); compiler emits explicit columns | Both original star probes and hidden CTE-star test |
| Column, wrong aggregate or literal labelled net_revenue accepted | Match metric-named expression ASTs to governed formulas; normalize only compiler scope wrappers; narrowly allow benign aggregate primitives | All three original formula probes and additional nested/wrong-formula tests |
| Exact name matching prevented unfamiliar intent from reaching the grader | Resolve wording once using the existing three tools; validate schema, ID and policy before using the resolved ID | Five dev paraphrase regressions plus invalid resolution cases |
| Refund adjustment mistaken for requested refunds metric | Treat a single-word metric mentioned after an adjustment modifier as an operand; resolve the requested intent through governed tools | Refund-only intent and explicit competing-metric regressions remain intact |
| Corrected exact definition could be dropped again by reranking | Retain the validated metric definition within the bounded correction evidence; still require a sufficient grade | Deliberately hostile reranker regression |
| Duplicate RRF results shifted later ranks | Deduplicate before assigning ranks within each retriever | Controlled duplicate/tie/missing-result test |
| SQLite generation connection remained open | Close explicitly while preserving transaction semantics | Fixed-seed warehouse/integrity suite and resource-warning checks |
| Cached local models still attempted metadata network access | Prefer local files; fetch the same configured model only on a cache miss | Cached provider constructor and availability tests |
| Provider/DB failures produced an indistinct generic error | Separate safe timeout, rate-limit and DB messages, without exception text | Injected failure tests with private strings |
| Live estimate could exceed the approved budget before running | Refuse before confirmation if conservative estimate exceeds the cap | Over-budget test asserts no confirmation/provider call |
| Provider-cached input tokens priced at ordinary input rate | Support optional cached-input rate and reported provider cache tokens | Exact Decimal tier-pricing test |

The validator's original result changes from 26/32 caught to 32/32, with 0/10
false positives. Original benign probes include simple aggregate primitives;
accepting those does not prove every catalog business rule for arbitrary SQL.
Production continues to use only the deterministic governed compiler, whose
scoped metric expressions are checked against full catalog formulas.

## Corrective safety

Semantic resolution uses `select_metric`, `request_clarification` or `refuse`;
there is no new exposed function and no LLM SQL. Resolution cannot authorize an
unknown metric, disallowed dimension, filter value or grain. The original
question remains unchanged. An accepted resolution is reused for final tool
selection to avoid another paid call, then checked again through the normal
safety chain. The selected ID must match the grade's accepted metric.

No confidence threshold, call cap, round cap or rewrite-fidelity rule was
relaxed. Exact catalog lookup during correction supplies the selected definition
as evidence, not as a sufficient verdict. Ambiguity still clarifies, and failed
grading still abstains. LLM semantic mistakes remain possible; offline oracle
results cannot establish live intent accuracy.

## Reports and paid-run controls

Baseline: `eval/reports/dev_prompt3_dev_verified/`.
Verified after run: `eval/reports/dev_hardening_verified_oracle/`.
Comparison: `eval/reports/hardening_before_after.md`.
Intermediate diagnostics are retained with distinct names; they are not the
final after result.

Verified final test result: **574 passed, 1 opt-in live smoke skipped**. Line
coverage is **91.81%**, branch coverage **81.01%**, combined pytest-cov coverage
**89.32%** across app and UI. See
[coverage summary](../eval/reports/hardening_coverage/summary.md).

On the 55 dev oracle cases, corrective outcome accuracy improved from 90.91%
to 100%, answer exactness from 83.33% to 100%, refusal precision from 75% to
100%, and unnecessary refusals from five to zero. Refusal recall stayed 100%.

The live smoke is skipped by default even when a key is present. Opt-in is
`pytest -s --run-live-smoke tests/test_live_smoke.py`; it uses the same interactive
confirmation and budget gates as the CLI. Without a key it skips. Normal
coverage runs cannot accidentally spend API budget.

User-supplied project prices, not assumed market prices:

```dotenv
MODEL_PRICES_JSON='{"gpt-6-luna":{"input_per_million":0.10,"output_per_million":0.50,"cached_input_per_million":0.01}}'
```

Put that line in your own `.env`. `.env.example` contains an empty assignment
and a placeholder-only shape comment. No credential is printed or changed.
For ten questions in one corrective-mode run, at most 40 uncached calls,
960,000 input-budget tokens and 60,000 output-budget tokens yield a conservative
USD 0.126 estimate. The approved hard cap is USD 0.15. Cache hits reduce actual
spend. Estimated cost above the cap is rejected before any paid call; each call
also reserves a conservative amount against the remaining ledger. Failure
reservations remain conservative if billing usage is unknown.

The reviewed live subset includes all five unfamiliar paraphrases and dev cases
for answer/clarification/refusal/empty result. Use `--case-ids` to select those
reviewed dev IDs; IDs outside dev are rejected. No paid run begins without the
user's separate confirmation after the estimate. Actual live results are
reported separately and compared with oracle results on exactly matching IDs.

The user approved that run after the estimate. It completed ten cases with
20 paid attempts and USD 0.0051802 ledger spend. Live outcome accuracy was 60%
and answer exactness 50%, versus 100%/100% on matching oracle cases. All four
disagreements were safe clarifications, with zero incorrect numeric answers and
zero unnecessary refusals. No second paid run was performed. See
[live failure analysis](../eval/reports/hardening_live_analysis.md) and the
separate live/oracle comparison for the remaining semantic-grading limitations.

## Remaining risks and assumptions

- Catalog definitions and the frozen warehouse remain authoritative. Reference
  labels and canonical arguments are hand-authored and still benefit from review.
- Unit retrieval tests use stubs; cross-encoder semantic ordering, model access,
  provider latency and hardware-dependent cold loading require environment checks.
- Formula matching guards named metric expressions, not a general proof of SQL
  meaning. Arbitrary SQL is never an application input.
- A model can misunderstand intent while returning valid governed arguments;
  strict tool schemas and catalog constraints cannot eliminate semantic errors.
- Coverage reports distinguish uncovered infrastructure/error branches. High
  coverage is not a security proof, and a ten-question live run is not a robust
  estimate of general accuracy.
- Live results may be partial if the budget or provider fails. Cached responses
  are labelled separately from new paid attempts; disk hits cost zero.
