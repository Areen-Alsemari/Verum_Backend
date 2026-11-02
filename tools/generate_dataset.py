"""Generate supported reference data and a portable training bundle for all eight roles.

The committed recipe supplies the campaign seed and configuration; existing sources may be reused.
Large outputs remain local and this command never trains agents or publishes artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verum.training.pipeline import generate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--roof-reference", type=Path)
    args = parser.parse_args()
    report = generate_dataset(
        args.root, workers=args.workers, campaign=args.campaign, roof_reference=args.roof_reference
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
