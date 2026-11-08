"""Convert historical asset role-view records into agent request inputs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from verum.agents.common.loader import iter_role_records
from verum.agents.runner.facts import reference_facts

ROLE = "historical_asset_intelligence"


def build_historical_asset_input(
    role_input: dict[str, Any], *, reference_evidence_id: str
) -> dict[str, Any]:
    """Map a role-view input to the historical asset request payload."""
    reference = role_input["reference"]
    history = reference.get("history")
    return {
        "query_asset_ids": [role_input["query"]["asset_id"]],
        "assets": reference["assets"],
        "declared_facts": reference_facts(reference, reference_evidence_id),
        "history": [] if history is None else history,
        "reference_evidence_ids": [reference_evidence_id],
    }


def main() -> None:
    """Read one prepared record and summarize the converted payload."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--reference-evidence-id", required=True)
    args = parser.parse_args()

    record = next(iter_role_records(args.root, ROLE, "train"))
    payload = build_historical_asset_input(
        record.input, reference_evidence_id=args.reference_evidence_id
    )
    print(f"Queried asset: {payload['query_asset_ids'][0]}")
    print(f"Declared facts: {len(payload['declared_facts'])}")
    print(f"History records: {len(payload['history'])}")


if __name__ == "__main__":
    main()