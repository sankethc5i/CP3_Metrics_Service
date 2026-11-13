# Benchmark artifacts

Current hardening artifacts:

- [Verified before/after](hardening_before_after.md): dev oracle results and separately labelled live comparison.
- [After oracle report](dev_hardening_verified_oracle/report.md): all five modes, 55 dev questions.
- [Approved live run](dev_hardening_live10/report.md) and [live failure analysis](hardening_live_analysis.md): ten reviewed dev questions, USD 0.0051802 spend.
- [Coverage](hardening_coverage/summary.md): 574 passing tests, one opt-in live skip, 91.81% lines / 81.01% branches.

The older statements below describe the Prompt 3 baseline before this hardening
phase. Intermediate `dev_hardening_after_oracle/` and
`dev_hardening_final_oracle/` directories are diagnostics, superseded by
`dev_hardening_verified_oracle/`.

- **Canonical five-mode dev comparison:** [dev_prompt3_dev_verified/report.md](dev_prompt3_dev_verified/report.md).
  CSV summaries, per-question scores, PNG/SVG charts, all traces and failed-case
  analysis are in the same directory. 55 dev questions; no paid model calls.
- [Independent arithmetic audit](ground_truth_audit.md): raw-record net-revenue
  and category allocation cross-check, with a worked multi-line order.
- [Validator-only diagnostic](dev_prompt3_validator/report.md): 32 negatives,
  10 benign queries, zero SQL execution and zero model calls.
- [Retrieval-only CLI check](dev_prompt3_retrieval_zero_calls/report.md): three
  dev cases, lookup mode, no function calls or grading.
- `dev_prompt3_offline_dev/` is the preliminary run, retained for provenance.
  Its ambiguity relevance scoring incorrectly included gross revenue when net
  revenue was already qualified, and omitted units_sold in one region-ambiguity
  case. The canonical comparison corrects that scorer bug without changing
  questions, SQL, reference answers or system behavior.

No locked system evaluation or live OpenAI evaluation has been performed.
Ground-truth labels for the locked split were authored using independent SQL;
they were not used to measure or tune system behavior. Offline oracle replay
scores do not establish live language-model selection accuracy.
