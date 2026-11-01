"""Audit diagnostic training readiness without generating or editing data.

The command exits unsuccessfully when engineering evidence or structural qualification is missing.
A research verification result is kept separate from approval for physical diagnostic training.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verum.training import audit_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.resolve().is_relative_to(args.root.resolve()):
        raise ValueError("readiness reports must stay outside the source dataset")
    report = audit_dataset(args.root, args.evidence)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("training ready" if report["training_ready"] else "training blocked")
    print("\n".join(report["blockers"]))
    raise SystemExit(0 if report["training_ready"] else 2)


if __name__ == "__main__":
    main()
