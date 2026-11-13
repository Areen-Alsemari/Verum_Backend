"""Check that tracing changes no message of the runner on the 181-window sample.

Inputs: the stored bundles of an earlier run of the sample and the train and validation role
views, opened through the audit hook and the guard of the detector experiments. Output: JSON on
stdout and with --out: for a pass with tracing off and one with a recording sink, the windows whose
requests, reports, issues and notes equal the stored ones, the spans recorded and any window label
found in them. Assumptions: the sample is rebuilt with its fixed seed, so windows and order are
the stored ones; labels are read only to look for them in the spans; the test split is refused.
Source: the tracing design report, section 5.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_runner_sample as sample  # noqa: E402

KEYS = ("requests", "reports", "issues", "notes")
SWITCH, KEY = "LANGSMITH_TRACING", "LANGSMITH_API_KEY"


class Recorder:
    """A sink that keeps every span, standing in for the LangSmith client."""

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    def start(self, name: str, inputs: Any, tags: Any, metadata: Any, parent: Any) -> int:
        self.spans.append({"name": name, "inputs": inputs, "tags": list(tags),
                           "metadata": dict(metadata), "parent": parent})  # fmt: skip
        return len(self.spans) - 1

    def end(self, handle: int, outputs: Any, error: str | None) -> None:
        self.spans[handle].update(outputs=outputs, error=error)


def canon(value: Any) -> str:
    """Canonical text of a value as the sample script stored it."""
    return json.dumps(json.loads(json.dumps(value, default=str)), sort_keys=True)


def stored(folder: Path, window_id: str) -> dict[str, Any]:
    """The requests, reports, issues and notes of one stored bundle."""
    with gzip.open(folder / "bundles" / f"{window_id}.json.gz", "rt", encoding="utf-8") as handle:
        contents = json.load(handle)
    return {key: contents[key] for key in KEYS}


def fresh(bundle: Any) -> dict[str, Any]:
    """The same four parts of a bundle that has just been run."""
    return {key: getattr(bundle, key) for key in KEYS}


def label_words(window: dict[str, Any]) -> set[str]:
    """The truth strings of a window: fault types, mechanisms and the faulty assets."""
    return {*window["fault_types"], *window["mechanisms"], *window["assets"]}


def run_pass(
    windows: list[dict[str, Any]], summaries: dict[str, Any], reference: Any, sha: str,
    folder: Path, traced: bool,
) -> dict[str, Any]:
    """Run every window of the sample in its chain and compare it with the stored bundle."""
    from verum.agents.runner import AssessmentLog, run_analysis, verify_bundle
    from verum.agents.runner.tracing import Tracer

    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for w in windows:
        episodes[w["episode_id"]].append(w)
    same = {key: 0 for key in KEYS}
    spans = leaks = children = windows_run = 0
    for e, (_, members) in enumerate(sorted(episodes.items())):
        log, last = AssessmentLog(), None
        for w in sorted(members, key=lambda x: x["position"]):
            case_id = f"E{e:04d}"
            log = sample.pad_gap(log, case_id, last, w["position"])
            sink = Recorder()
            snap = sample.make_snapshot(case_id, w, summaries[w["window_id"]], reference, sha)
            extra: dict[str, Any] = {"tracer": Tracer(sink)} if traced else {}
            bundle = run_analysis(snap, "runtime", allow_placeholders=False, recent=log, **extra)
            verify_bundle(bundle, allow_placeholders=False)
            log, last, windows_run = bundle.assessments, w["position"], windows_run + 1
            old, new = stored(folder, w["window_id"]), fresh(bundle)
            for key in KEYS:
                same[key] += canon(old[key]) == canon(new[key])
            text = json.dumps(sink.spans, default=str)
            spans += len(sink.spans)
            children += sum(s["parent"] == 0 for s in sink.spans)
            leaks += sum(word in text for word in label_words(w))
    return {
        "traced": traced, "windows": windows_run, "identical": same, "spans": spans,
        "children_of_the_parent": children, "label_words_found_in_spans": leaks,
    }


def main() -> int:
    """Rebuild the sample, run it twice and print the comparison."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stored", type=Path, required=True, help="folder of the earlier run")
    parser.add_argument("--release", type=Path, default=sample.DEFAULT_RELEASE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if os.environ.get(SWITCH, "").lower() == "true" or os.environ.get(KEY):
        raise SystemExit("run this check with the tracing variables unset")
    sample.install_audit()
    sample.install_guard()
    from verum.agents.common import file_sha256

    ref_path = args.release / "knowledge" / "public_reference.json"
    reference = json.loads(ref_path.read_text())
    sha = file_sha256(ref_path)
    val, val_ep = sample.load_split(args.release, "validation")
    windows = sample.build_sample(val, val_ep)
    trn, trn_ep = sample.load_split(args.release, "train")
    windows += sample.build_train_sanity(trn, trn_ep)
    ids = {w["window_id"] for w in windows}
    summaries = sample.summary_of(val, ids) | sample.summary_of(trn, ids)
    result: dict[str, Any] = {"windows_in_sample": len(windows)}
    result["passes"] = [
        run_pass(windows, summaries, reference, sha, args.stored, on) for on in (False, True)
    ]
    result["test_split_files_touched"] = sample.touched_test_split()
    result["guard"] = sample.guard_summary()
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    ok = all(
        p["windows"] == len(windows) and all(v == len(windows) for v in p["identical"].values())
        for p in result["passes"]
    )
    clean = not result["test_split_files_touched"] and not result["guard"]["rejected"]
    return 0 if ok and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
