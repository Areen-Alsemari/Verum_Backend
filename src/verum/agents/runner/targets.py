"""The targets and the window-derived constraint checks of the Agent 6 request.

Agent 6 is asked only about the catalogue assets that the hypotheses of Agent 5 implicate: an
asset named by a component, or a tag that is itself an asset of the reference. Nothing else is
guessed; in particular a level transmitter is not mapped to its tank, because the reference
declares no such link. A constraint check is derived only when its precondition can be read from
the observation window of the same request, and only as a pass; a failed precondition is left
unknown, because Agent 8 reads a failed plan precondition as a conflict. The permit-like
preconditions need an approved request, which stays with the caller.
"""

from __future__ import annotations

from typing import Any, Final

from verum.agents.runner.prepare import FEATURES, Prepared

RECEIPT_ACTION: Final = "ACT-INSP-06"
RECEIPT_TEXT: Final = "Tank out of receipt mode"
PUMP_ACTION: Final = "ACT-INSP-03"
PUMP_TEXT: Final = "Pump running under load for at least 20 min"


def implicated_assets(diagnosis: dict[str, Any] | None, asset_ids: set[str]) -> list[str]:
    """Catalogue assets named by the hypotheses, in rank order and without repeats."""
    if diagnosis is None or diagnosis.get("result") is None:
        return []
    found: list[str] = []
    for hypothesis in diagnosis["result"].get("hypotheses", []):
        for component in hypothesis["components"]:
            for name in (component.get("asset_id"), component.get("tag_id")):
                if name in asset_ids and name not in found:
                    found.append(str(name))
    return found


def signals_of(prep: Prepared) -> dict[str, dict[str, Any]]:
    """The signals of the observation window by tag."""
    summary = prep.observations.get("summary") or {}
    return {s["tag_id"]: s for s in summary.get("signals", []) if isinstance(s, dict)}


def read_state(signals: dict[str, dict[str, Any]], tag: str) -> bool | None:
    """The latest on-off state of a tag if it was measured and good, else None."""
    signal = signals.get(tag)
    if signal is None or signal.get("latest_availability") != "measured":
        return None
    if signal.get("latest_quality") != "good":
        return None
    value = signal.get("latest_value")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def inlet_valves(connections: list[dict[str, Any]], tank: str) -> list[str]:
    """Valves that the declared connections place directly before a nozzle of the tank."""
    return sorted({c["from_node"] for c in connections if str(c["to_node"]).startswith(f"{tank}:")})


def receipt_check_outcome(prep: Prepared, tank: str) -> str | None:
    """'pass' if every inlet valve of the tank reads closed in the window, 'open' if one reads
    open, and None if it cannot be read."""
    valves = inlet_valves(prep.connections, tank)
    if not valves:
        return None
    states = [read_state(signals_of(prep), valve) for valve in valves]
    if any(state is None for state in states):
        return None
    return "pass" if not any(states) else "open"


def catalogue_has(prep: Prepared, action_id: str, text: str, kind: str) -> bool:
    """Whether the catalogue lists the precondition for an action on this kind of asset."""
    return any(
        a["action_id"] == action_id and a["target_kind"] == kind and text in a["preconditions"]
        for a in prep.catalog
    )


def stopped_pumps(prep: Prepared, targets: list[str]) -> int:
    """Implicated pumps whose run state reads stopped: a failure that is left unknown."""
    kinds = {a["asset_id"]: a["kind"] for a in prep.assets}
    signals = signals_of(prep)
    pumps = [t for t in targets if kinds.get(t) == "pump"]
    listed = catalogue_has(prep, PUMP_ACTION, PUMP_TEXT, "pump")
    return sum(listed and read_state(signals, p) is False for p in pumps)


def derive_checks(
    prep: Prepared, targets: list[str], supplied: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Checks readable from the window, and the count of failures that were left unknown."""
    kinds = {a["asset_id"]: a["kind"] for a in prep.assets}
    derived: list[dict[str, Any]] = []
    withheld = 0
    for tank in (t for t in targets if kinds.get(t) == "tank"):
        if not catalogue_has(prep, RECEIPT_ACTION, RECEIPT_TEXT, "tank"):
            continue
        outcome = receipt_check_outcome(prep, tank)
        scope = f"{RECEIPT_ACTION}-{tank}-"
        known = any(
            c["description"] == RECEIPT_TEXT and c["check_id"].startswith(scope) for c in supplied
        )
        withheld += outcome == "open"
        if outcome == "pass" and not known:
            derived.append(
                {
                    "check_id": f"{scope}WINDOW-01",
                    "description": RECEIPT_TEXT,
                    "outcome": "pass",
                    "evidence_ids": [FEATURES],
                }
            )
    return derived, withheld + stopped_pumps(prep, targets)
