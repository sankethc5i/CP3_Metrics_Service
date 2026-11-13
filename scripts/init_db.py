"""Build the synthetic warehouse; invoke from the repository root."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.config import DATABASE_PATH, SEED
from app.db.seed import create_warehouse


def main() -> None:
    """Create a new database and print deterministic row counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path",type=Path,default=DATABASE_PATH)
    parser.add_argument("--seed",type=int,default=SEED)
    args = parser.parse_args()
    print(json.dumps(create_warehouse(args.path,args.seed),indent=2))


if __name__ == "__main__":
    main()
