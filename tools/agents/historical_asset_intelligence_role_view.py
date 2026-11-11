"""Adapt and evaluate historical asset role-view records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from verum.agents.common.loader import iter_role_records
from verum.agents.historical_asset_intelligence.adapter import build_historical_asset_input
from verum.agents.historical_asset_intelligence.agent import HistoricalAssetIntelligenceAgent
from verum.contracts.agent_interfaces import contract_directory

ROLE = "historical_asset_intelligence"


def _matches_reference(report: dict[str, Any], role_input: dict[str, Any]) -> bool:
    """Check the queried asset and history against the prepared reference."""
    result = report["result"]
    if report["status"] not in {"complete", "degraded"} or result is None:
        return False

    asset_id = role_input["query"]["asset_id"]
    reference = role_input["reference"]
    assets = [row for row in reference["assets"] if row["asset_id"] == asset_id][-1:]
    history = [
        row for row in (reference.get("history") or []) if assets and row["asset_id"] == asset_id
    ]
    return (
        result["asset_records"] == assets
        and result["missing_asset_ids"] == ([] if assets else [asset_id])
        and result["history"] == history
        and all(fact["asset_id"] == asset_id for fact in result["facts"])
    )


def main() -> int:
    """Run the agent against each prepared record and count valid results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--split", choices=("all", "train", "validation", "test"), default="all")
    parser.add_argument("--reference-evidence-id")
    parser.add_argument("--as-of-s", type=float, help="Override the request cutoff in seconds")
    args = parser.parse_args()

    path = contract_directory() / "examples" / f"{ROLE}.request.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    evidence_id = args.reference_evidence_id or template["input"]["reference_evidence_ids"][0]
    if not any(row["evidence_id"] == evidence_id for row in template["evidence"]):
        parser.error("reference evidence ID is not present in the example request")

    agent = HistoricalAssetIntelligenceAgent()
    splits = ("train", "validation", "test") if args.split == "all" else (args.split,)
    total = valid = crashes = 0
    statuses: Counter[str] = Counter()
    for split in splits:
        split_total = split_valid = 0
        for index, record in enumerate(iter_role_records(args.root, ROLE, split), 1):
            split_total += 1
            try:
                request = deepcopy(template)
                if args.as_of_s is not None:
                    request["context"]["as_of_s"] = args.as_of_s
                else:
                    context = record.input.get("context") or {}
                    query = record.input["query"]
                    for fields in (context, query, record.input):
                        cutoff = fields.get("as_of_s", fields.get("cutoff_s"))
                        if cutoff is not None:
                            request["context"]["as_of_s"] = cutoff
                            break
                request["input"] = build_historical_asset_input(
                    record.input, reference_evidence_id=evidence_id
                )
                report = agent.run(request)
                statuses[report["status"]] += 1
                if _matches_reference(report, record.input):
                    split_valid += 1
                    continue
                print(f"{split} row {index}: report did not match the reference")
            except Exception as exc:
                crashes += 1
                print(f"{split} row {index}: crash: {exc}")
        total += split_total
        valid += split_valid
        print(f"{split}: {split_valid}/{split_total} valid")

    print(f"Total: {valid}/{total} valid")
    print(f"Statuses: {dict(sorted(statuses.items()))}; crashes: {crashes}")
    return 0 if total > 0 and valid == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
