"""The true state of an episode at any time, read from the evaluator file of true quantities.

Numbers are interpolated linearly between rows and a state (a flag, a text, a whole number) is the
value of the last row at or before the time. Across a pre-event and post-event pair the value is
that of the side on which the time falls. After the last row the process state is held, and the
fault entries follow their trajectories and hold their last value. This module is evaluator side
and its output never reaches an agent except through a model and a closed schema.

See D102.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from verum.vapour.model import MechanicalFault, Parameters, mechanical_state, validate_graph

FILE = "inspection_truth.jsonl.gz"
FAULT_TRUTH = "fault_truth.jsonl.gz"
SCENARIO = "scenario.json"
State = dict[str, Any]


def _read(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _blend(a: Any, b: Any, w: float) -> Any:
    """Linear blend of the numbers of two rows; every other value is that of ``a``."""
    if isinstance(a, dict):
        return {k: _blend(v, b[k], w) for k, v in a.items()}
    if isinstance(a, list):
        return [_blend(x, y, w) for x, y in zip(a, b, strict=True)]
    if type(a) is float and type(b) is float:
        return a + (b - a) * w
    return a


class Truth:
    """True state of one episode, from its evaluator directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        scenario = json.loads((directory / SCENARIO).read_text(encoding="utf-8"))
        self.episode_id: str = directory.name
        self.seed: int = int(scenario["seed"])
        self.horizon_s: float = float(scenario["duration_s"])
        self.rows = _read(directory / FILE)
        if not self.rows:
            raise ValueError("inspection truth has no recorded process states")
        self.coverage_end_s = min(self.horizon_s, float(self.rows[-1]["t_sim_s"]))
        self._faults = _read(directory / FAULT_TRUTH) if (directory / FAULT_TRUTH).exists() else []
        self.mechanical_faults: list[MechanicalFault] | None = None
        self.mechanical_parameters: Parameters | None = None
        mechanical_path = directory / "mechanical_faults.json"
        if mechanical_path.exists():
            mechanical = json.loads(mechanical_path.read_text(encoding="utf-8"))
            if set(mechanical) != {"schema_version", "hidden", "parameter_hash", "faults"}:
                raise ValueError("unknown or missing mechanical sidecar fields")
            if mechanical["hidden"] is not True or mechanical["schema_version"] != "1.0.0":
                raise ValueError("invalid mechanical fault sidecar")
            parameters = Parameters()
            if mechanical["parameter_hash"] != parameters.hash:
                raise ValueError("mechanical parameter hash differs from the episode")
            self.mechanical_parameters = parameters
            self.mechanical_faults = [MechanicalFault(**r) for r in mechanical["faults"]]
            validate_graph(self.mechanical_faults)

    # --- time ----------
    def _bracket(self, t: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
        left = 0
        for i, r in enumerate(self.rows):
            if r["t_sim_s"] > t:
                break
            if r["t_sim_s"] < t or r["side"] != "pre_event":
                left = i
        right = self.rows[left + 1] if left + 1 < len(self.rows) else None
        return self.rows[left], right

    def state(self, t: float) -> State:
        """The true state at time ``t`` (an episode time in seconds)."""
        left, right = self._bracket(min(t, self.horizon_s))
        t_eff = min(t, self.horizon_s)
        if right is None or t_eff <= left["t_sim_s"]:
            state = json.loads(json.dumps(left))
        else:
            w = (t_eff - left["t_sim_s"]) / (right["t_sim_s"] - left["t_sim_s"])
            state = _blend(left, right, w)
        if t > self.horizon_s:
            self._follow_trajectories(state, t)
        state["t_sim_s"] = t
        if self.mechanical_faults is not None and self.mechanical_parameters is not None:
            state["mechanical"] = mechanical_state(
                self.mechanical_faults, t, self.mechanical_parameters
            )
        return dict(state)

    # --- faults ----------
    def _follow_trajectories(self, state: State, t: float) -> None:
        """Past the horizon the fault entries follow their trajectories, held at the last knot."""
        for entry, truth in zip(state["faults"], self._faults, strict=True):
            severity = self.severity(truth, t)
            base = truth["physical_parameter_modified"]["baseline_value"]["value"]
            full = truth["physical_parameter_modified"]["fault_value_at_severity_one"]["value"]
            entry["severity"] = severity
            entry["parameter_value"] = base + severity * (full - base)
            if truth["fault_type"] == "PUMP_HEAD_DEGRADATION":
                state["pumps"][truth["asset_id"]]["head_scale"] = entry["parameter_value"]

    @staticmethod
    def severity(fault_truth: dict[str, Any], t: float) -> float:
        """Severity of a fault-truth row at ``t``: piecewise linear, last value held."""
        knots = fault_truth["severity_trajectory"]["knots"]
        s = t - fault_truth["onset_t_sim_s"]
        if s < knots[0][0]:
            return 0.0
        for (s0, v0), (s1, v1) in zip(knots, knots[1:], strict=False):
            if s <= s1:
                return float(v0 + (v1 - v0) * (s - s0) / (s1 - s0)) if s1 > s0 else float(v1)
        return float(knots[-1][1])
