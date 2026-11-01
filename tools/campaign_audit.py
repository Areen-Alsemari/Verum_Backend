"""Build a separate evaluator work queue for unaudited campaign faults.

No labels or observations are changed. The output identifies original fault instances and
coverage cells, and records the exact manifest from which the queue was derived.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from verum.evaluation.campaign_audit import write_inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = write_inventory(args.root, args.output)
    print(f"{result['pending_faults']} faults in {result['pending_episodes']} episodes")
    print(f"{len(result['coverage_cells'])} coverage cells; {len(result['gaps'])} gap slots")


if __name__ == "__main__":
    main()
