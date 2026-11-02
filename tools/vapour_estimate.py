"""Calculate evaluator-only vapour estimates from explicit source-bearing inputs.

Routine windows and normal liquid-heel landings use separate methods and applicability checks.
Missing physical inputs stop the calculation; no estimate is emitted as a sensor observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verum.params import ParamValue, UnresolvedParameter
from verum.provenance import config_hash, git_state
from verum.vapour.landing import heel_landing_episode
from verum.vapour.window import estimate_window


def estimate(document: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a declared normal-operation method, without constructing missing properties."""
    kind = document["estimate_type"]
    if kind == "routine_window":
        return estimate_window(document)
    if kind == "liquid_heel_landing":
        parameters = {k: ParamValue.from_mapping(v) for k, v in document["parameters"].items()}
        flags = {
            k: document[k]
            for k in (
                "heel",
                "normal_supported_landing",
                "freely_vented",
                "maintained",
                "refill_completed",
            )
        }
        return heel_landing_episode(**parameters, **flags)
    raise ValueError("unknown estimate type")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    try:
        result = estimate(json.loads(raw))
    except (KeyError, TypeError, ValueError, UnresolvedParameter) as exc:
        parser.exit(2, f"vapour estimate blocked: {exc}\n")
    commit, dirty = git_state()
    result |= {
        "input_file_sha256": hashlib.sha256(raw).hexdigest(),
        "code_commit": commit,
        "code_dirty": dirty,
        "config_hash": config_hash(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Evaluator estimate written; physical training qualification remains separate.")


if __name__ == "__main__":
    main()
