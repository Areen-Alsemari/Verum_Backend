"""Generate coupled roof-boundary references with process-covered manual inspections.

The command preserves original parent splits and records rejected attempts without replacement.
No structural failure criterion, damaged-emission factor or diagnostic agent is introduced.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from verum.training.reference import build_roof_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    report = build_roof_reference(args.source, args.output, workers=args.workers)
    print(f"{report['attempts']} attempts; {report['rejected_attempts']} rejected")


if __name__ == "__main__":
    main()
