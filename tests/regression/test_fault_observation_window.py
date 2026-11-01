"""Initial fault conditions and arbitrary observed onset times without imposed failure rates.

Legacy campaign timing remains unchanged. Independent series-path arithmetic checks the initial
pump condition, rather than assuming an already-running plant starts healthy.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
from pathlib import Path

import pytest
from scipy.optimize import brentq

import _reference_hydraulics as reference
from verum.faults import FaultSet, FaultSpec, violations
from verum.hydraulics import HydraulicModel
from verum.sim.episode import run_episode
from verum.sim.scenario import load_scenario
from verum.truth import read_rows


@pytest.mark.parametrize("onset", [0.0, 15.0, 3590.0])
def test_observation_window_does_not_force_the_legacy_middle_interval(onset: float) -> None:
    """Observation windows admit early, late and initial faults; legacy timing refuses them.

    Independent: yes, because the literal times fall outside the old 600 to 1800 s interval.
    """
    fault = FaultSpec("SENSOR_DRIFT", "bias", "LT-101", onset, None, 0.01)
    assert violations([fault], [], ["LT-101"], 3600.0)
    assert violations([fault], [], ["LT-101"], 3600.0,
                      timing_profile="observation_window") == []


def test_physical_steps_are_initial_conditions_only() -> None:
    """An already degraded pump is allowed initially; an interior physical step is refused.

    Independent: yes, because an initial state and a discontinuous in-window failure are distinct.
    """
    initial = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 0., None, 0.8)
    assert violations([initial], [], [], 30., timing_profile="observation_window") == []
    interior = dataclasses.replace(initial, onset_s=15.)
    assert violations([interior], [], [], 30., timing_profile="observation_window")
    assert violations([initial], [], [], 30., timing_profile="unknown")


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1.])
def test_invalid_window_times_are_refused(value: float) -> None:
    """Boolean, nonfinite and negative times cannot describe a fault's observation window.

    Independent: yes, because each value violates the numeric time domain.
    """
    fault = FaultSpec("SENSOR_DRIFT", "bias", "LT-101", value, None, 0.01)
    assert violations([fault], [], ["LT-101"], 3600., timing_profile="observation_window")
    fault = dataclasses.replace(fault, onset_s=0., ramp_s=value)
    assert violations([fault], [], ["LT-101"], 3600., timing_profile="observation_window")


@pytest.mark.slow
def test_initial_degraded_pump_matches_the_independent_series_path(tmp_path: Path) -> None:
    """The first recorded pump flow reflects pre-existing degradation and its onset is censored.

    Independent: yes, because a separate scalar series-path reference supplies the expected flow.
    """
    model = HydraulicModel.load()
    scenario = dataclasses.replace(
        load_scenario("S0-A"), scenario_id="INITIAL-PUMP", duration_s=30.,
                                   initial_mode="DELIVER_102_A", demand_process=False,
                                   variability_profile="off")
    fault = FaultSpec("PUMP_HEAD_DEGRADATION", "head_scale", "P-101A", 0., None, 0.8)
    result = run_episode(scenario.scenario_id, tmp_path, model, scenario, FaultSet((fault,)),
                         fault_timing_profile="observation_window")
    assert not result.rejected
    rows = read_rows(result.directory, "hydraulic_state")
    pump = next(r["payload"] for r in rows if r["t_sim_s"] == 0 and
                r["record_type"] == "pump_state" and r["element_id"] == "P-101A")

    def residual(q: float) -> float:
        need = reference.required_head(q, 7., 10.0609, 200000.,
                                       reference.tank2_reference_fittings_segments())
        return 0.8 * (54. - 12. * (q * 3600. / 300.) ** 2) - need

    assert pump["flow_m3s"] == pytest.approx(brentq(residual, 1e-6, 0.5), rel=2e-3)
    window = json.loads((result.directory / "fault_window.json").read_text())
    with gzip.open(result.directory / "fault_truth.jsonl.gz", "rt") as handle:
        truth = json.loads(next(handle))
    assert window["left_censored_fault_instance_ids"] == [truth["fault_instance_id"]]
    assert truth["onset_t_sim_s"] == 0.
