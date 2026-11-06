"""Write a chained set of requests and responses produced by running the runner on one snapshot.

Every request after the first carries real, hashed upstream reports. By default every role is
answered by its placeholder, so the files do not change while owners replace their agents; use the
installed agents option to run whatever is currently installed. The check option compares the files
on disk with a fresh run and exits with status 1 on any difference.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from verum.agents.common import ROLES, StubAgent, file_sha256, iter_role_records
from verum.agents.runner import Snapshot, run_analysis, verify_bundle
from verum.contracts.agent_interfaces import Agent
from verum.contracts.paths import repo_root

DEFAULT_RELEASE = Path("data/reference_release_v2/verum_reference_v2")
DEFAULT_OUTPUT = Path("tests/agents/fixtures/chained")
CASE_ID = "chained-example"
ROLE = "predictive_health"


def _text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _snapshot(release: Path) -> Snapshot:
    reference_file = release / "knowledge" / "public_reference.json"
    record = next(iter_role_records(release, ROLE, "train"))
    return Snapshot(
        case_id=CASE_ID, revision=0, as_of_s=300.0, summary=record.input["observations"],
        reference=json.loads(reference_file.read_text(encoding="utf-8")),
        reference_snapshot_sha256=file_sha256(reference_file),
    )


def build(release: Path, installed: bool) -> dict[str, str]:
    """Run all roles once and return the file contents keyed by file name."""
    agents: dict[str, Agent] | None = None
    if not installed:
        agents = {role: StubAgent(role) for role in ROLES}
    bundle = run_analysis(_snapshot(release), "runtime", agents=agents)
    verified = verify_bundle(bundle)
    if bundle.issues:
        raise SystemExit(f"the run reported issues: {bundle.issues}")
    files = {}
    for role, request in bundle.requests.items():
        files[f"{role}.request.json"] = _text(request)
        files[f"{role}.response.json"] = _text(verified.responses[role])
    order = list(bundle.requests)
    index = {
        "context": verified.context, "order": order,
        "report_ids": {r: verified.responses[r]["report_id"] for r in order},
    }
    files["index.json"] = _text(index)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=repo_root() / DEFAULT_RELEASE)
    parser.add_argument("--output", type=Path, default=repo_root() / DEFAULT_OUTPUT)
    parser.add_argument("--installed-agents", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = build(args.release, args.installed_agents)
    if args.check:
        stale = [n for n, text in files.items() if not (args.output / n).exists()
                 or (args.output / n).read_text(encoding="utf-8") != text]
        print(json.dumps({"files": len(files), "stale": stale, "passed": not stale}))
        return 1 if stale else 0
    args.output.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (args.output / name).write_text(text, encoding="utf-8")
    print(json.dumps({"files": len(files), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
