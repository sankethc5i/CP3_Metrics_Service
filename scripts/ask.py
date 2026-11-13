"""Command-line entry point to the same API-backed service used by Streamlit."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.service import create_service


def main() -> None:
    """Submit one question and print its structured response including trace ID."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--mode",choices=["lookup","naive","hybrid","hybrid_rerank","corrective"])
    args = parser.parse_args()
    settings = load_settings()
    if args.mode:
        settings = settings.model_copy(update={"rag_mode":args.mode})
    response = create_service(settings).ask(args.question)
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
