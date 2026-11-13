# Hardening before/after (dev only)

Both full-set runs below use oracle arguments; live results appear separately. Locked tests were not run.

| Mode | Outcome accuracy before | After | Answer exactness before | After | Refusal precision before | After | Unnecessary refusals before | After |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lookup | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 0 |
| naive | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 0 |
| hybrid | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 0 |
| hybrid_rerank | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 0 |
| corrective | 90.91% | 100.00% | 83.33% | 100.00% | 75.00% | 100.00% | 5 | 0 |

Original SQL negatives: 26/32 → 32/32. Benign false positives: 0.00% → 0.00%.

The missing projections/set-operation/formula restrictions were fixed in the validator; original probes were not removed.

Refusal precision = correct refusals / all refusals. Refusal recall = correct refusals / expected refusals. Corrective refusal recall is retained, while its unnecessary refusals are measured explicitly.

## Live vs oracle

- corrective: 10 matched dev questions. Live outcome accuracy 60.00%, answer exactness 50.00%; matched oracle outcome accuracy 100.00%, answer exactness 100.00%.
- Paid attempts: 20; ledger spend USD 0.0051802; budget stopped: False. Incomplete runs are reported on completed cases only.
- These small live results are diagnostic, not population accuracy estimates. See the live report for failures and cache sources.
