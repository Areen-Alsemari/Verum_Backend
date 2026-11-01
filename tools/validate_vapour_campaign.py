"""Validate a generated mechanical extension against its original hydraulic campaign.

The report records integrity, split, observation-preservation and inspection-workflow checks.
Its scope is explicitly restricted synthetic verification rather than physical certification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verum.vapour.validation import validate_extension


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = validate_extension(args.base, args.root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
