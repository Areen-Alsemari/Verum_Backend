"""Render the files of a chained run: each role's request and response, and an index.

The files are indented, key-sorted JSON with a trailing newline, so that a change shows as a small
readable difference. By default every role is answered by its placeholder, which keeps the files
independent of how far the owners have come.
"""

from __future__ import annotations

import json
from typing import Any

from verum.agents.common import ROLES, StubAgent
from verum.agents.runner.bundle import BundleError, verify_bundle
from verum.agents.runner.run import run_analysis
from verum.agents.runner.snapshot import Snapshot
from verum.contracts.agent_interfaces import Agent


def render(value: Any) -> str:
    """Return the canonical text of a fixture file."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def chained_files(snapshot: Snapshot, *, installed: bool = False) -> dict[str, str]:
    """Run all roles once on a snapshot and return the file contents keyed by file name."""
    agents: dict[str, Agent] | None = None
    if not installed:
        agents = {role: StubAgent(role) for role in ROLES}
    bundle = run_analysis(snapshot, "runtime", agents=agents)
    verified = verify_bundle(bundle)
    if bundle.issues:
        raise BundleError(f"the run reported issues: {bundle.issues}")
    files: dict[str, str] = {}
    for role, request in bundle.requests.items():
        files[f"{role}.request.json"] = render(request)
        files[f"{role}.response.json"] = render(verified.responses[role])
    order = list(bundle.requests)
    files["index.json"] = render({
        "context": verified.context, "order": order,
        "report_ids": {r: verified.responses[r]["report_id"] for r in order},
    })
    return files
