"""Compare topology agent reports with the prepared role-view targets."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from verum.agents.common.loader import iter_role_records
from verum.agents.topology_dependency.agent import (
    TopologyDependencyAgent,
    build_topology_input,
)
from verum.contracts.agent_interfaces import contract_directory

ROLE = "topology_dependency"
SPLITS = ("train", "validation", "test")


def main() -> int:
    """Evaluate each selected split and report mismatches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--split", choices=("all", *SPLITS), default="all")
    args = parser.parse_args()

    path = contract_directory() / "examples" / f"{ROLE}.request.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    evidence_ids = template["input"]["reference_evidence_ids"]
    agent = TopologyDependencyAgent()
    splits = SPLITS if args.split == "all" else (args.split,)

    total = matched = 0
    for split in splits:
        split_total = split_matched = 0
        for index, record in enumerate(iter_role_records(args.root, ROLE, split), 1):
            request = deepcopy(template)
            request["input"] = build_topology_input(
                record.input, reference_evidence_ids=evidence_ids
            )
            report = agent.run(request)
            result = report["result"]
            expected = record.target
            split_total += 1

            if (
                result is not None
                and sorted(
                    (edge["edge_id"], edge["from_node"], edge["to_node"])
                    for edge in result["direct_connections"]
                )
                == sorted(
                    (edge["edge_id"], edge["from_node"], edge["to_node"])
                    for edge in expected["direct_connections"]
                )
                and result["actual_routing_confirmed"]
                is expected["actual_routing_confirmed"]
            ):
                split_matched += 1
            else:
                asset = record.input["query"]["asset_id"]
                print(f"Mismatch: {split} row {index}, asset {asset}")

        print(f"{split}: {split_matched}/{split_total} matched")
        total += split_total
        matched += split_matched

    print(f"Total: {matched}/{total} matched")
    return 0 if total > 0 and matched == total else 1


if __name__ == "__main__":
    raise SystemExit(main())