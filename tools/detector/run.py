"""Command line: score, evaluate, diagnose (post-hoc controls) and report.

Options: --release (release folder), --work (work folder), --out (results file).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    """Dispatch the two stages."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["score", "evaluate", "diagnose", "report"])
    parser.add_argument("--release", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--key", choices=["lineup", "conditions"], default="lineup")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    if args.stage == "score":
        import pipeline

        meta = pipeline.run(args.release, args.work, args.key)
        skip = ("ids", "episodes", "kind", "part_names")
        print(json.dumps({k: v for k, v in meta.items() if k not in skip}, indent=1))
    elif args.stage == "evaluate":
        import evaluate

        evaluate.run(args.work, args.out)
    elif args.stage == "diagnose":
        import diagnostics

        diagnostics.run(args.release, args.work, args.out)
    else:
        import report

        report.run(args.results, args.diagnostics, args.work, args.out)


if __name__ == "__main__":
    main()
