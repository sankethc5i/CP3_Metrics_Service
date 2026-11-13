"""Eight zero-cost DEV oracle examples; no model downloads or API calls."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DATABASE_PATH, ROOT, Settings
from app.evaluation.dataset import load_cases
from app.evaluation.oracle import OracleModel
from app.observability.trace import redact
from app.service import create_service

IDS = ("simple-01", "simple-02", "grouped-02", "ratio-01", "ambiguous-02",
       "ambiguous-03", "unsupported_metric-02", "filter_value-05")


def main() -> None:
    """Replay authored selections through the real pipeline and show one trace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--output", type=Path, help="Optional compact Markdown artifact")
    args = parser.parse_args()
    _, cases = load_cases(ROOT/"eval/questions.yaml", args.database)
    by_id = {case["id"]: case for case in cases}
    lines = ["# Eight-question offline demo", "", "DEV oracle arguments; zero paid calls. Lookup retrieval; no model downloads.", "",
             "| Question | Expected | Actual |", "|---|---|---|"]
    first = None
    with tempfile.TemporaryDirectory(prefix="metrics-demo-") as directory:
        base = Path(directory)
        service = create_service(Settings(rag_mode="lookup",database=args.database,
            trace_dir=base/"traces",cache_dir=base/"embeddings",llm_cache_dir=base/"llm",model_cache_dir=base/"models"))
        for identifier in IDS:
            case = by_id[identifier]
            service.model = OracleModel(case)
            response = service.ask(case["question"])
            lines.append(f"| {case['question']} | {case['expected_outcome']} | {response.outcome} |")
            if response.outcome != case["expected_outcome"]:
                raise RuntimeError("Offline demo disagrees with the verified DEV outcome.")
            if first is None:
                first = response
    lines += ["", "## First question: real pipeline trace", "", "```json",
              json.dumps(redact({"outcome":first.outcome,"value":first.value,
                "metric_definition":first.metric_definition,"sql":first.sql,
                "trace_id":str(first.trace_id),"trace":first.trace}),indent=2), "```", ""]
    text = "\n".join(lines)
    if args.output:
        args.output.write_text(text,encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
