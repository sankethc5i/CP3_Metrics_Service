"""CLI entry point: python scripts/evaluate.py --mode all (offline dev by default)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.runner import main

if __name__ == "__main__":
    try:
        main()
    except (ValueError, EOFError, KeyboardInterrupt) as error:
        raise SystemExit(str(error) if not isinstance(error, KeyboardInterrupt) else "Evaluation interrupted.") from None
