# Handoff verification and final metrics

Verified 2026-11-13 on Windows / Python 3.14.3. No new paid calls.

## Measured success metrics

| Run / mode | Questions | Answer exactness | Refusal precision / recall | Validator catch | p95 ms | Definition attribution |
|---|---:|---:|---:|---:|---:|---:|
| [Fresh DEV oracle](../eval/reports/handoff/fresh-dev/report.md) / lookup | 55 | 100% (n=30) | 100% / 100% | 100% (32 probes) | 147.29 | 100% (n=30) |
| [Historical DEV oracle](../eval/reports/dev_hardening_verified_oracle/report.md) / corrective | 55 | 100% (n=30) | 100% / 100% | 100% (32 probes) | 592.18 | 100% (n=30) |
| [Historical DEV live](../eval/reports/dev_hardening_live10/report.md) / corrective | 10 | 50% (n=6) | 100% / 100% | 100% (32 probes) | 12308.04 | 100% (n=3) |
| [LOCKED oracle; one run](../eval/reports/handoff/locked-once/report.md) / corrective | 22 | 100% (n=12) | 100% / 83.3% | 100% (32 probes) | 532.62 | 100% (n=12) |

Oracle uses hand-authored function arguments, not live language understanding. Answer exactness is measured against independent reference SQL on expected-answer cases. Refusal precision is correct refusals/all refusals; recall is correct refusals/expected refusals. Definition attribution covers returned answer cases, so the live 100% attribution value does not imply successful answers to every question. Validator false positives are 0/10 benign probes in all four reports; the same separate SQL probe suite is reused.

Latency is per-question pipeline latency, excluding install, model warmup and the separate retrieval probe. Historical runs used earlier dependency versions; latency differences are not evidence of a model-quality improvement. All reports use local sentence-transformers/all-MiniLM-L6-v2; corrective runs use cross-encoder/ms-marco-MiniLM-L6-v2. Historical live model: gpt-6-luna, 10 DEV questions, USD 0.0051802 spent previously. This task spent USD 0.

The one locked invocation used all 22 held-out questions in corrective mode, entirely oracle-sourced; paid calls = 0. Failures: 1. No application/catalog/question changes or tuning followed. The holdout is now consumed; future independent claims require a newly authored holdout. [Compact outcome record](../eval/reports/handoff/locked-outcomes.json).

## Fresh-install proof

- Created a new virtualenv under Windows TEMP, outside the checkout; installed the existing full pinned requirements-lock.txt. No new package choices; existing .env and .venv were not modified.
- pip check passed. Full suite: **597 passed, 1 opt-in live smoke skipped**, 183.44 seconds. Tests ran with paid credentials disabled.
- init_db.py generated 160 customers, 72 products, 2,400 sessions, 400 orders, 580 order_items and 43 returns. Generated database SHA-256 matched the verified snapshot.
- Headless Streamlit on isolated port 8517 returned HTTP 200 for / and /_stcore/health, then stopped; UI rendering is also covered by AppTest. User command remains port 8501.
- Completed one offline DEV lookup pass on all 55 DEV cases, plus the eight-question demo. Fresh local-model smoke encoded a 384-dimensional vector and scored one cross-encoder pair with networking disabled.
- Existing public model weights were reused read-only for compatibility; a fresh first-download path was not tested. Internet is needed once for uncached weights. All newly generated DBs, caches, raw reports and install logs stayed in TEMP.
- The sandbox initially blocked a temporary demo trace write; rerunning with external-temp access succeeded. No installation, test or application failure remained.
- Packaging fixes: environment-backed external cache/trace paths; AS_OF_DATE validates the frozen snapshot; optional external --report-root. Tests precede the single locked run.

The external temporary virtualenv, database, caches and raw logs were deleted and absence verified. Cleanup is confirmed in [fresh-install.json](../eval/reports/handoff/fresh-install.json).

## Assumptions and remaining limitations

- Local synthetic-data prototype; MIT license assumes contributor ownership approval. Repository publication/push is not part of this task.
- Windows/Python 3.14.3 is verified; macOS/Linux and other Python versions are not. Direct pins are portable intent; the complete lock is Windows resolution.
- Historical live exactness remains only 50%; oracle success cannot establish live accuracy. See the original failure analysis; no live rerun was performed.
- Single metric, frozen date, capped result groups, order-date refund attribution; no production auth/global quota or automatic retention. Six Moderate and one Low dependency advisories remain intentionally unfixed: [security report](security-report.md). The final working-tree scan covered 2,230 files and 20 JSONL files; the sole configured-credential location was expected .env:2, with no detected copies elsewhere.

## Handoff contents

README.md; pinned runtime/dev requirements plus resolved lock; blank .env.example; scripts/init_db.py and Windows run.ps1; eight-question demo with trace; docs index; CONTRIBUTING.md; MIT LICENSE; Windows offline CI; ignored secrets/databases/weights/caches/large reports. The project map is in the README.

[Machine-readable metrics](../eval/reports/handoff/metrics.csv). Historical detailed artifacts remain in place; only compact new Markdown/CSV/JSON records are retained.
