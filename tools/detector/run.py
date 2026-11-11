"""Command line: score, evaluate, diagnose, report; grouped CV stages; C3 stages.

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


def _lineup(a: Namespace) -> None:
    import lineup_facts

    lineup_facts.run(a.release, a.out)


def _c3report(a: Namespace) -> None:
    import c3_text

    a.out.write_text(c3_text.render(a.work))


def _c3params(a: Namespace) -> None:
    import c3_params

    c3_params.run(a.release, a.out)


def _c3char(a: Namespace) -> None:
    import c3_char

    c3_char.run(a.work, a.out)


STAGES = {
    "score": _score,
    "evaluate": _evaluate,
    "diagnose": _diagnose,
    "report": _report,
    "cv": _cv,
    "cveval": _cveval,
    "cvcompare": _cvcompare,
    "cvreport": _cvreport,
    "c3char": _c3char,
    "lineupfacts": _lineup,
    "c3report": _c3report,
    "c3params": _c3params,
}


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
