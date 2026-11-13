"""Compare frozen before/after DEV artifacts and separately label live evidence."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT
from app.evaluation.metrics import aggregate


def main() -> None:
    """Write a reproducible comparison from saved results without rerunning any model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-report", type=Path)
    args = parser.parse_args()
    base = json.loads((ROOT/"eval/reports/dev_prompt3_dev_verified/results.json").read_text(encoding="utf-8"))
    after = json.loads((ROOT/"eval/reports/dev_hardening_verified_oracle/results.json").read_text(encoding="utf-8"))
    assert base["split"] == after["split"] == "dev"
    lines = ["# Hardening before/after (dev only)", "",
             "Both full-set runs below use oracle arguments; live results appear separately. Locked tests were not run.", "",
             "| Mode | Outcome accuracy before | After | Answer exactness before | After | Refusal precision before | After | Unnecessary refusals before | After |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mode in base["modes"]:
        b = aggregate(base["modes"][mode]["cases"])
        a = aggregate(after["modes"][mode]["cases"])
        lines.append(f"| {mode} | {b['outcome_correctness']:.2%} | {a['outcome_correctness']:.2%} | "
                     f"{b['answer_exactness']:.2%} | {a['answer_exactness']:.2%} | "
                     f"{b['refusal_precision']:.2%} | {a['refusal_precision']:.2%} | {b['unnecessary_refusals']} | {a['unnecessary_refusals']} |")
    b, a = base["validator"], after["validator"]
    lines += ["", f"Original SQL negatives: {sum(r['rejected'] for r in b['cases'] if r['kind']=='bad')}/{b['bad_count']} → "
              f"{sum(r['rejected'] for r in a['cases'] if r['kind']=='bad')}/{a['bad_count']}. "
              f"Benign false positives: {b['false_positive_rate']:.2%} → {a['false_positive_rate']:.2%}.", "",
              "The missing projections/set-operation/formula restrictions were fixed in the validator; original probes were not removed.", "",
              "Refusal precision = correct refusals / all refusals. Refusal recall = correct refusals / expected refusals. "
              "Corrective refusal recall is retained, while its unnecessary refusals are measured explicitly.", "", "## Live vs oracle", ""]
    if args.live_report:
        live = json.loads(args.live_report.read_text(encoding="utf-8"))
        if live["split"] != "dev" or not live["method"].startswith("live"):
            raise ValueError("Only an explicitly labelled live DEV report may be compared")
        for mode, data in live["modes"].items():
            ids = {r["id"] for r in data["cases"]}
            matched = [r for r in after["modes"][mode]["cases"] if r["id"] in ids]
            actual, oracle = aggregate(data["cases"]), aggregate(matched)
            lines += [f"- {mode}: {len(ids)} matched dev questions. Live outcome accuracy {actual['outcome_correctness']:.2%}, "
                      f"answer exactness {actual['answer_exactness']:.2%}; matched oracle outcome accuracy "
                      f"{oracle['outcome_correctness']:.2%}, answer exactness {oracle['answer_exactness']:.2%}."]
        lines += [f"- Paid attempts: {live['paid_calls']}; ledger spend USD {live['spent_usd']}; "
                  f"budget stopped: {live['budget_stopped']}. Incomplete runs are reported on completed cases only.",
                  "- These small live results are diagnostic, not population accuracy estimates. See the live report for failures and cache sources."]
    else:
        lines += ["Not run: awaiting explicit paid-call confirmation. Oracle scores do not imply live accuracy."]
    target = ROOT/"eval/reports/hardening_before_after.md"
    target.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
