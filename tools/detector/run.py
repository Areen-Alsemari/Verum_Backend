"""Command line with two stages: score (fit and score) and evaluate (metrics and controls).

Options: --release (release folder), --work (work folder), --out (results file).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    """Dispatch the two stages."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["score", "evaluate"])
    parser.add_argument("--release", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "score":
        import pipeline

        meta = pipeline.run(args.release, args.work)
        skip = ("ids", "episodes", "kind", "part_names")
        print(json.dumps({k: v for k, v in meta.items() if k not in skip}, indent=1))
    else:
        import evaluate

        evaluate.run(args.work, args.out)


if __name__ == "__main__":
    main()
