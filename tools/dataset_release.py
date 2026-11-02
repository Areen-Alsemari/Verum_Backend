"""Build, verify and materialize portable reference-model data for the eight Verum roles.

These commands create data views only and never instantiate or train an agent.
Physical release gates remain separate from the reference-model tasks.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from verum.training.dataset import build_dataset_release, iter_role_examples, verify_dataset_release
from verum.training.packaging import (
    materialize_roles,
    package_training,
    verify_roles,
    verify_training_archive,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--workers", type=int, default=1)
    build.add_argument("--inspection-source", type=Path, action="append", default=[])
    verify = commands.add_parser("verify")
    verify.add_argument("root", type=Path)
    views = commands.add_parser("materialize")
    views.add_argument("root", type=Path)
    views.add_argument("--role", required=True)
    views.add_argument("--split", choices=("train", "validation", "test"), required=True)
    views.add_argument("--output", type=Path, required=True)
    all_views = commands.add_parser("materialize-all")
    all_views.add_argument("root", type=Path)
    role_check = commands.add_parser("verify-roles")
    role_check.add_argument("root", type=Path)
    pack = commands.add_parser("package")
    pack.add_argument("root", type=Path)
    pack.add_argument("--output", type=Path, required=True)
    archive_check = commands.add_parser("verify-archive")
    archive_check.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        report = build_dataset_release(
            args.source,
            args.output,
            workers=args.workers,
            inspection_sources=tuple(args.inspection_source),
        )
        print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify_dataset_release(args.root), indent=2))
    elif args.command == "materialize-all":
        print(json.dumps(materialize_roles(args.root), indent=2))
    elif args.command == "verify-roles":
        print(json.dumps(verify_roles(args.root), indent=2))
    elif args.command == "package":
        print(json.dumps(package_training(args.root, args.output), indent=2))
    elif args.command == "verify-archive":
        print(json.dumps(verify_training_archive(args.archive), indent=2))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with gzip.open(args.output, "xt", encoding="utf-8") as handle:
            for row in iter_role_examples(args.root, args.role, args.split):
                handle.write(json.dumps(row, allow_nan=False) + "\n")
                count += 1
        print(json.dumps({"examples": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
