"""Command line: score, evaluate, diagnose, report; cv, cveval, cvcompare, cvreport (grouped CV).

Options: --release (release folder), --work (work folder), --out (results file), --key (regime
key of the score stage), --spec (comma-separated enhancements E1 to E4 of the cv stage).
"""

from __future__ import annotations

import argparse
import json
from argparse import Namespace
from pathlib import Path


def _score(a: Namespace) -> None:
    import pipeline

    meta = pipeline.run(a.release, a.work, a.key)
    skip = ("ids", "episodes", "kind", "part_names")
    print(json.dumps({k: v for k, v in meta.items() if k not in skip}, indent=1))


def _evaluate(a: Namespace) -> None:
    import evaluate

    evaluate.run(a.work, a.out)


def _diagnose(a: Namespace) -> None:
    import diagnostics

    diagnostics.run(a.release, a.work, a.out)


def _report(a: Namespace) -> None:
    import report

    report.run(a.results, a.diagnostics, a.work, a.out)


def _cv(a: Namespace) -> None:
    import cv
    from systems import Spec

    flags = set(a.spec.split(",")) - {""}
    cv.run(a.release, a.work, Spec("E1" in flags, "E2" in flags, "E3" in flags, "E4" in flags))


def _cveval(a: Namespace) -> None:
    import cv_eval

    cv_eval.run(a.work, a.out)


def _cvcompare(a: Namespace) -> None:
    import cv_eval

    for tag, name in (("oof", "C4"), ("val", "C4"), ("oof", "C3"), ("val", "C3")):
        print(tag, name, json.dumps(cv_eval.compare_systems(a.results, a.work, tag, name)))


def _cvreport(a: Namespace) -> None:
    import cv_text

    a.out.write_text(cv_text.render(a.work))


STAGES = {
    "score": _score, "evaluate": _evaluate, "diagnose": _diagnose, "report": _report,
    "cv": _cv, "cveval": _cveval, "cvcompare": _cvcompare, "cvreport": _cvreport,
}  # fmt: skip


def main() -> None:
    """Dispatch one stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=list(STAGES))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--key", choices=["lineup", "conditions"], default="lineup")
    parser.add_argument("--spec", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    STAGES[args.stage](args)


if __name__ == "__main__":
    main()
