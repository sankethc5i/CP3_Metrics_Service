# Teammate guide

Read [AGENTS.md](AGENTS.md), [architecture](docs/02-architecture.md) and
[security findings](docs/security-report.md) before changing the pipeline.

1. Create a branch; install the pinned development requirements in an isolated environment.
2. Keep catalog formulas governed and parameterized; preserve all six safety layers.
3. Add a regression only for changed behavior; run `python -m pytest -q` and the
   offline dev lookup evaluation. Use dev questions for tuning.
4. Describe changes, validation, assumptions and unknowns in the pull request.
5. Never commit `.env`, databases, downloaded weights, cache payloads or traces.
   Scan staged files before publishing. Do not paste credentials into issues.

The locked split has now been measured for handoff. Do not tune on those results;
future releases need a newly authored holdout before claiming independent accuracy.
Live tests/evaluation require explicit approval and prices; ordinary tests and
the demo make no paid calls. Preserve historical reports and label oracle vs live.

MIT is the proposed project license; confirm contributor ownership before public
publication. Dependencies, downloaded models and datasets retain their own licenses.
