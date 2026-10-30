"""Healthy-variability profiles: off and v1 unchanged, and the v2 regimes and receipt set-point
process.

The regime drawer and the set-point process are checked by statistics over many seeds, short engine
runs of the version 2 scenarios, and the stored pumping-minimum tables. The profiles off and v1
reproduce the earlier engine rows bit for bit, which the digests taken before version 2 existed
confirm. The hand values and the digests are described in the "Healthy-variability profiles" section
of the verification notes.

See D23, D51 and D73.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from typing import Any

import numpy as np
import pytest
from scipy import stats

import _fault_cases as fc
from verum.contracts import validate
from verum.contracts.errors import ContractError
from verum.hydraulics import HydraulicModel
from verum.hydraulics.pumping_minimum import pumping_minimum_level, stratum_filename
from verum.lineups import load_lineup_table
from verum.params import ParamValue
from verum.rng import RandomStreams
from verum.sim.config import SimConfig, load_sim_config
from verum.sim.demand import DemandProcess
from verum.sim.engine import Engine
from verum.sim.scenario import load_scenario, parse_scenario
from verum.sim.variability import (
    RegimeDemand,
    RegimeDrawer,
    SetpointDeviation,
    check_receipt_headroom,
    regime_value,
    resolve_profile,
)
from verum.truth import ListSink

CFG = load_sim_config()
LOW, HIGH = CFG["demand_total_factor_min_v2"], CFG["demand_regime_max"]
GOLDEN = {
    "S0-A": "8e50dabe047966b60e4590aabf4669bf54910dcd3c7d1dfa601a008420800606",
    "S0-F": "80b16b69f9fd1027a82183c12d29bca01138a1b7d282d943f201a9b2fc7fb023",
    "S0-B": "7c83d8413679786f60d47b229459c419cd00dd3f058d6f14667f2458769f105e",
}


def _digest(rows: dict[str, list[dict[str, Any]]]) -> str:
    def canon(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: canon(v) for k, v in o.items() if k != "episode_id"}
        if isinstance(o, (list, tuple)):
            return [canon(v) for v in o]
        return o

    return hashlib.sha256(json.dumps(canon(rows), sort_keys=True, default=str).encode()).hexdigest()


def _draw_many(seeds: range, count: int) -> list[Any]:
    out = []
    for seed in seeds:
        drawer = RegimeDrawer(seed, CFG)
        t = 0.0
        for i in range(count):
            regime, redraws = drawer.draw(i, t, lambda v: None)
            assert redraws == []
            out.append(regime)
            t = regime.plateau_end_s
    return out


# --- profile selection ----------
def test_a_file_without_the_key_keeps_its_earlier_meaning() -> None:
    """A scenario file without a profile key means off without the demand process and v1 with it.
    Independent: yes, because the expected meanings are the stated rule.
    """
    assert resolve_profile(None, False) == "off"
    assert resolve_profile(None, True) == "v1"
    assert load_scenario("S0-A").variability_profile == "off"
    assert load_scenario("S0-F").variability_profile == "v1"
    for sid in ("S0-A-v2", "S0-B-v2", "S0-C-v2"):
        assert load_scenario(sid).variability_profile == "v2"


@pytest.mark.parametrize(
    ("declared", "demand"), [("off", True), ("v1", False), ("v2", False), ("v3", True)]
)
def test_a_profile_that_disagrees_with_the_demand_switch_is_refused(
    declared: str, demand: bool
) -> None:
    """A declared profile that disagrees with the demand switch is refused. Independent: yes,
    because the expected outcome is the validation rule.
    """
    with pytest.raises(ContractError):
        resolve_profile(declared, demand)


def test_the_v2_copies_differ_from_the_shipped_files_only_in_profile_and_seed() -> None:
    """Each version 2 copy differs from its shipped scenario only in the profile and the seed.
    Independent: yes, because the two files are compared with each other.
    """
    for sid in ("S0-A", "S0-B", "S0-C"):
        a, b = load_scenario(sid), load_scenario(f"{sid}-v2")
        same = dataclasses.replace(
            b,
            scenario_id=a.scenario_id,
            seed=a.seed,
            description=a.description,
            demand_process=a.demand_process,
            variability_profile=a.variability_profile,
        )
        assert same == a


# --- off and v1 are unchanged ----------
@pytest.mark.slow
@pytest.mark.parametrize("sid", sorted(GOLDEN))
def test_profiles_off_and_v1_reproduce_the_earlier_rows_bit_for_bit(
    model: HydraulicModel, sid: str
) -> None:
    """The engine rows of the off and v1 scenarios match digests taken before version 2 existed.
    Independent: yes, because the digests are of the earlier output and not of the new code.
    """
    engine, outcome = fc.run(model, sid, 900.0)
    assert outcome.rejection is None
    assert _digest(engine.sink.rows) == GOLDEN[sid]  # type: ignore[attr-defined]
    assert outcome.regimes == [] and outcome.regime_redraws == []


# --- regime statistics ----------
def test_regime_values_are_log_uniform_on_the_configured_range() -> None:
    """Regime values are log-uniform on the configured range, with the mean and variance of the hand
    formulas. Independent: yes, because the statistics use scipy and hand arithmetic.
    """
    regimes = _draw_many(range(40), 50)
    logs = np.array([math.log(r.value) for r in regimes])
    assert logs.min() >= math.log(LOW) and logs.max() <= math.log(HIGH)
    assert logs.mean() == pytest.approx((math.log(LOW) + math.log(HIGH)) / 2, abs=0.05)
    sd = (math.log(HIGH) - math.log(LOW)) / math.sqrt(12.0)
    assert logs.std() == pytest.approx(sd, rel=0.04)
    ks = stats.kstest(logs, stats.uniform(math.log(LOW), math.log(HIGH / LOW)).cdf)
    assert ks.pvalue > 0.01


def test_regime_dwells_are_uniform_between_600_and_1800_s() -> None:
    """Regime dwell times are uniform between 600 and 1800 s with a mean of 1200 s. Independent:
    yes, because the expected mean is hand arithmetic.
    """
    dwell = np.array([r.dwell_s for r in _draw_many(range(40), 50)])
    assert dwell.min() >= 600.0 and dwell.max() <= 1800.0
    assert dwell.mean() == pytest.approx(1200.0, abs=25.0)
    assert stats.kstest(dwell, stats.uniform(600.0, 1200.0).cdf).pvalue > 0.01


def test_the_first_regime_has_no_ramp_and_the_others_ramp_for_60_s() -> None:
    """The first regime has no ramp and each later regime is entered over 60 s. Independent: yes,
    because the expected durations are the stated configuration.
    """
    regimes = _draw_many(range(3), 6)
    for r in regimes:
        assert r.ramp_s == (0.0 if r.index == 0 else 60.0)
        assert r.plateau_start_s == r.t_start_s + r.ramp_s
    assert [r.index for r in regimes[:6]] == list(range(6))


def test_the_ramp_between_regimes_is_linear_and_continuous() -> None:
    """The ramp between two regimes is linear and continuous, so its midpoint is the mean of the two
    values. Independent: yes, because the expected values are hand arithmetic.
    """
    regimes = _draw_many(range(1), 4)
    for prev, nxt in zip(regimes, regimes[1:], strict=False):
        t0 = nxt.t_start_s
        assert regime_value(regimes, t0 - 1e-9) == pytest.approx(prev.value, rel=1e-9)
        assert regime_value(regimes, t0) == pytest.approx(prev.value, rel=1e-12)
        for a in (0.25, 0.5, 0.75):
            expected = prev.value + a * (nxt.value - prev.value)
            assert regime_value(regimes, t0 + 60.0 * a) == pytest.approx(expected, rel=1e-12)
        assert regime_value(regimes, nxt.plateau_start_s) == pytest.approx(nxt.value, rel=1e-12)
        assert regime_value(regimes, nxt.plateau_end_s - 1e-6) == pytest.approx(nxt.value)


def test_a_regime_is_a_function_of_the_seed_and_the_index_only() -> None:
    """A regime depends on the seed and the index only. Independent: yes, because equality is the
    property.
    """
    a, b = _draw_many(range(5, 6), 5), _draw_many(range(5, 6), 5)
    assert a == b
    assert _draw_many(range(6, 7), 5) != a
    # Drawing regime 3 alone gives the regime drawn in sequence: no generator state is carried.
    alone, _ = RegimeDrawer(5, CFG).draw(3, a[3].t_start_s, lambda v: None)
    assert alone == a[3]


def test_the_regime_draws_do_not_disturb_the_other_streams() -> None:
    """Drawing regimes leaves the demand stream unchanged. Independent: yes, because the stream is
    compared before and after.
    """
    seed = 20261001
    before = RandomStreams(seed).stream("demand").standard_normal(5)
    _draw_many(range(seed, seed + 1), 5)
    assert np.array_equal(RandomStreams(seed).stream("demand").standard_normal(5), before)
    ou_v1 = DemandProcess(True, RandomStreams(seed), 3600.0, 0.05, 1800.0, 0.8, 1.25)
    ou_v2 = DemandProcess(True, RandomStreams(seed), 3600.0, 0.05, 1800.0, 0.8, 1.25)
    assert ou_v1.log_path.tolist() == ou_v2.log_path.tolist()


def test_a_candidate_that_fails_the_gate_is_redrawn_and_recorded() -> None:
    """A candidate regime value that fails the gate is redrawn and recorded with its reason.
    Independent: yes, because the gate is written in the test.
    """
    drawer = RegimeDrawer(11, CFG)
    regime, redraws = drawer.draw(2, 0.0, lambda v: "too_high" if v > 2.0 else None)
    assert regime.value <= 2.0 and regime.draws == len(redraws) + 1
    assert all(r.value > 2.0 and r.reason == "too_high" for r in redraws)
    assert [r.attempt for r in redraws] == list(range(1, len(redraws) + 1))
    same, again = drawer.draw(2, 0.0, lambda v: "too_high" if v > 2.0 else None)
    assert (same, again) == (regime, redraws)
    with pytest.raises(ContractError):
        drawer.draw(0, 0.0, lambda v: "never")


# --- receipt set-point process ----------
def test_the_receipt_deviation_has_the_configured_spread_correlation_and_clip() -> None:
    """The receipt set-point deviation has a standard deviation of 0.02 and a lag-600 s correlation
    of exp(-1), within sampling bounds. Independent: yes, because the statistics are hand derived.
    """
    # 200 paths of 3600 s with a correlation of 600 s hold about 200 x 3600 / 1200 = 600
    # independent samples, so the relative standard error of the spread is 1 / sqrt(2 x 600) =
    # 2.9 percent and the tolerance below is three of them.
    paths = np.array([SetpointDeviation(s, 3600.0, CFG).path for s in range(200)])
    assert paths.std() == pytest.approx(0.02, rel=0.09)
    lag = 600
    corr = float(np.mean(paths[:, :-lag] * paths[:, lag:]) / paths.var())
    assert corr == pytest.approx(math.exp(-1.0), abs=0.06)
    dev = SetpointDeviation(3, 3600.0, CFG)
    fractions = [dev.fraction(float(t)) for t in range(0, 3600, 7)]
    assert max(abs(f) for f in fractions) <= 0.06
    assert dev.effective(0.0, 100.0) == 0.0  # zero stays zero
    assert dev.effective(600.0, 100.0) == pytest.approx(600.0 * (1.0 + dev.fraction(100.0)))


def test_the_clip_binds_when_the_deviation_is_large() -> None:
    """With a large spread the deviation is clipped to its bounds. Independent: yes, because the
    expected bounds are the configured values.
    """
    wide = SimConfig(
        {
            **CFG.parameters,
            "receipt_setpoint_sigma_fraction": ParamValue.from_mapping(
                {**_raw("receipt_setpoint_sigma_fraction"), "value": 0.2}
            ),
        }
    )
    dev = SetpointDeviation(1, 3600.0, wide)
    values = [dev.fraction(float(t)) for t in range(0, 3600, 3)]
    assert max(values) == pytest.approx(0.06) and min(values) == pytest.approx(-0.06)


def _raw(name: str) -> dict[str, Any]:
    p = CFG.parameters[name]
    return {
        "value": p.value, "unit": p.unit, "status": p.status,
        "evidence_tag": p.evidence_tag, "provenance_id": p.provenance_id,
    }  # fmt: skip


def test_the_headroom_screen_uses_the_largest_clipped_set_point() -> None:
    """The headroom screen uses the largest clipped set-point, so 600 m3/h at 1.06 times passes and
    620 m3/h does not. Independent: yes, because the limit is the hand-derived 651.515 m3/h.
    """
    assert 600.0 * 1.06 == pytest.approx(636.0) and 620.0 * 1.06 == pytest.approx(657.2)
    check_receipt_headroom([0.0, 300.0, 600.0], 651.515, 0.06)
    with pytest.raises(ContractError):
        check_receipt_headroom([620.0], 651.515, 0.06)


def test_the_engine_limit_is_the_headroom_figure_of_the_tank_audit(model: HydraulicModel) -> None:
    """The engine's headroom limit equals the 651.515 m3/h of the tank headroom screen. Independent:
    yes, because the figure is hand arithmetic.
    """
    e = fc.engine(model, "S0-B-v2", 10.0)
    assert e._receipt_headroom_limit_m3h() == pytest.approx(651.515, abs=1e-3)


# --- the worst-case factor and the pumping-minimum tables ----------
def test_the_lower_bound_keeps_the_pump_five_m3h_inside_its_curve(model: HydraulicModel) -> None:
    """At the lower bound of the downstream factor the pump flow stays at least 5 m3/h inside its
    curve. Independent: no, because the flow comes from the steady solver.
    """
    from verum.graph import Lineup
    from verum.hydraulics import DeliveryBoundary, SteadyInputs, load_boundary_law_coefficient

    def flow(f_d: float) -> float:
        inputs = SteadyInputs(
            Lineup.of({"XV-S101", "XV-PAI", "XV-PAO"}, {"P-101A"}),
            {"TK-101": 12.0},
            "RVP_9_0",
            25.0,
            fitting_profile="reference_fittings",
            delivery=DeliveryBoundary(
                law_coefficient_m=load_boundary_law_coefficient("reference_fittings").value * f_d
            ),
        )
        pump = model.for_stratum("coastal").solve(inputs).pump
        assert pump is not None
        return pump.flow_m3h

    assert flow(0.6) == pytest.approx(348.07, abs=0.01)  # inside the margin of 5: the bound moves
    assert flow(LOW) <= 345.0 < flow(LOW - 1e-4)
    assert LOW == 0.6502


def test_the_v2_tables_never_lower_a_minimum_and_are_read_by_v2_scenarios() -> None:
    """The version 2 pumping-minimum tables never lower a minimum relative to the version 1 tables,
    and version 2 scenarios read them. Independent: yes, because only the ordering and the file
    choice are checked.
    """
    for atm in ("coastal", "inland"):
        for vol in ("RVP_9_0", "RVP_9_5", "RVP10"):
            old = json.loads((_config() / stratum_filename(atm, vol)).read_text(encoding="utf-8"))[
                "levels"
            ]
            new = json.loads(
                (_config() / stratum_filename(atm, vol, "v2")).read_text(encoding="utf-8")
            )["levels"]
            assert stratum_filename(atm, vol, "v2").endswith("_fd0p6502.json")
            for tank, per_temp in new.items():
                for temp, per_profile in per_temp.items():
                    for profile, per_coeff in per_profile.items():
                        for coeff, cell in per_coeff.items():
                            before = old[tank][temp][profile][coeff]["value"]
                            after = cell["value"]
                            if before is None:
                                assert after is None
                            elif after is not None:
                                assert after >= before - 1e-9
    record = pumping_minimum_level(
        "TK-101",
        25.0,
        "reference_fittings",
        4.0,
        None,
        stratum_filename("coastal", "RVP_9_0", "v2"),
    )
    assert record.value <= 9.0  # the reference level of S0-A-v2 passes


def _config() -> Any:
    from verum.contracts.paths import config_dir

    return config_dir()


# --- v2 engine runs ----------
def _engine(
    model: HydraulicModel,
    sid: str,
    duration: float,
    cfg: SimConfig | None = None,
    state: Any = None,
    sink: ListSink | None = None,
) -> Engine:
    scenario = dataclasses.replace(load_scenario(sid), duration_s=duration)
    return Engine(
        model, load_lineup_table(model.topology), scenario, cfg or CFG, sink or ListSink(),
        "EP-TEST", state,
    )  # fmt: skip


@pytest.mark.slow
def test_the_mass_ledger_closes_through_a_regime_ramp_and_the_pump_stays_inside_the_curve(
    model: HydraulicModel,
) -> None:
    """Through the first regime ramp the mass ledger closes and the pump stays inside its curve.
    Independent: yes, because closure and the pump limit are stated rules.
    """
    first, _ = RegimeDrawer(load_scenario("S0-A-v2").seed, CFG).draw(0, 0.0, lambda v: None)
    duration = float(math.ceil(first.plateau_end_s + 60.0 + 40.0))  # the first ramp and 40 s more
    engine = _engine(model, "S0-A-v2", duration)
    outcome = engine.run()
    assert outcome.rejection is None and outcome.final_t == duration
    ramp = outcome.regimes[1]
    assert ramp["t_start_s"] == first.plateau_end_s  # the ramp is inside the run
    assert ramp["plateau_start_s"] < duration
    sink: Any = engine.sink
    network = [r for r in sink.rows["mass_ledger"] if r["scope"] == "network"]
    assert len(network) > duration and all(r["closed"] for r in network)
    flows = [
        r["payload"]["flow_m3s"] * 3600.0
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "edge_state" and r["element_id"] == "E-D2"
    ]
    assert 0.0 < max(flows) <= 350.0 - CFG["pump_domain_margin_m3h"] + 1e-6


@pytest.mark.slow
def test_the_gate_redraws_are_recorded_in_the_events_and_the_outcome(
    model: HydraulicModel,
) -> None:
    """Regime redraws appear in the truth events and in the engine outcome. Independent: yes,
    because the expected records are written out in the test.
    """
    strict = SimConfig(
        {
            **CFG.parameters,
            "pump_min_stable_flow_m3h": ParamValue.from_mapping(
                {**_raw("pump_min_stable_flow_m3h"), "value": 250.0}
            ),
        }
    )
    engine = _engine(model, "S0-A-v2", 3600.0, strict)
    outcome = engine.run()
    assert outcome.rejection is None
    assert outcome.regime_redraws, "a flow floor of 250 m3/h must reject large factors"
    assert {r["reason"] for r in outcome.regime_redraws} == {"minimum_stable_flow"}
    assert all(r["draws"] >= 1 for r in outcome.regimes)
    sink: Any = engine.sink
    events = [r for r in sink.rows["events"] if r["event_type"] == "demand_regime"]
    assert len(events) == len(outcome.regimes)
    assert sum(len(e["payload"]["redraws"]) for e in events) == len(outcome.regime_redraws)
    # Hand: the flow at the accepted total factor 1.25 x value stays at or above 250 m3/h.
    assert max(r["value"] for r in outcome.regimes) < min(
        r["value"] for r in outcome.regime_redraws
    )


@pytest.mark.slow
def test_the_boundary_rows_record_the_regime_and_the_receipt_set_point(
    model: HydraulicModel,
) -> None:
    """The hidden boundary rows record the regime and the receipt set-point. Independent: yes,
    because the expected fields are written out in the test.
    """
    engine = _engine(model, "S0-B-v2", 400.0)
    outcome = engine.run()
    assert outcome.rejection is None
    sink: Any = engine.sink
    rows = sink.rows["boundary_state"]
    for row in rows[::50]:
        validate("boundary_state", row)
    late = [r for r in rows if r["t_sim_s"] >= 10.0]
    assert all(r["receipt_setpoint_nominal_m3h"] == 600.0 for r in late)
    eff = np.array([r["receipt_setpoint_effective_m3h"] for r in late])
    assert eff.min() >= 600.0 * 0.94 and eff.max() <= 600.0 * 1.06
    assert eff.std() > 0.0  # the set-point moves
    first = rows[0]
    assert first["demand_regime_value"] == pytest.approx(outcome.regimes[0]["value"])
    # The controller (time constant 2 s) follows the moving set-point: the receipt flow of the
    # truth rows is within 0.5 percent of the effective set-point once it has settled.
    flows = {
        r["t_sim_s"]: r["payload"]["flow_m3s"] * 3600.0
        for r in sink.rows["hydraulic_state"]
        if r["record_type"] == "edge_state"
        and r["element_id"] == "E001"
        and r["side"] != "pre_event"
    }
    errors = [
        abs(flows[r["t_sim_s"]] - r["receipt_setpoint_effective_m3h"]) / 600.0
        for r in late
        if r["t_sim_s"] in flows and r["t_sim_s"] >= 60.0
    ]
    assert max(errors) < 0.005


@pytest.mark.slow
def test_the_episode_record_carries_the_profile_only_for_v2(
    model: HydraulicModel, tmp_path: Any
) -> None:
    """Only the version 2 episode record carries the profile, the accepted regimes and the redrawn
    candidates. Independent: yes, because the expected keys are written out in the test.
    """
    from verum.sim.episode import run_episode

    scenario = dataclasses.replace(load_scenario("S0-A-v2"), duration_s=120.0)
    v2 = run_episode("S0-A-v2", tmp_path / "v2", model, scenario)
    doc = json.loads((v2.directory / "episode.json").read_text())
    validate("episode", doc)
    assert doc["variability_profile"] == "v2" and len(doc["demand_regimes"]) == 1
    assert doc["demand_regime_redraws"] == []
    plain = dataclasses.replace(load_scenario("S0-A"), duration_s=60.0)
    v0 = run_episode("S0-A", tmp_path / "v0", model, plain)
    doc0 = json.loads((v0.directory / "episode.json").read_text())
    validate("episode", doc0)
    assert "variability_profile" not in doc0 and "demand_regimes" not in doc0


def test_a_scenario_file_names_the_profile_in_its_own_field() -> None:
    """A scenario file names its profile in its own field, and a contradiction is refused.
    Independent: yes, because the expected outcome is the validation rule.
    """
    raw = json.loads((_config() / "scenarios" / "S0-B-v2.json").read_text())
    assert raw["variability_profile"] == "v2" and raw["demand_process"] is True
    raw["variability_profile"] = "off"
    with pytest.raises(ContractError):
        parse_scenario(raw)


def test_the_sensor_and_detector_streams_do_not_depend_on_the_profile(
    model: HydraulicModel,
) -> None:
    """The detector offset and the sensor streams are the same under profile v1 and v2 for the same
    seed. Independent: yes, because equality is the property.
    """
    v1 = fc.engine(model, "S0-A", 10.0, variability_profile="v1", demand_process=True)
    v2 = fc.engine(model, "S0-A-v2", 10.0, seed=load_scenario("S0-A").seed)
    assert v1.detector_offset == v2.detector_offset
    for tank in v1._lt:
        assert np.array_equal(v1._lt[tank].times, v2._lt[tank].times)
        assert np.array_equal(v1._lt[tank].noise, v2._lt[tank].noise)
    assert isinstance(v1.demand, DemandProcess) and isinstance(v2.demand, RegimeDemand)
    assert np.array_equal(v1.demand.log_path, v2.demand.ou.log_path)


def test_sg0_reads_the_table_of_the_profile(model: HydraulicModel) -> None:
    """The engine gate reads the pumping-minimum table of the scenario's profile, so a 6.5 m start
    passes under v1 and is rejected under v2. Independent: yes, because the two minima are stored
    values.
    """
    levels = {"TK-101": 6.5, "TK-102": 7.0, "TK-103": 5.0}
    v1 = fc.run(model, "S0-A", 5.0, temperature_c=45.0, tank_levels_m=levels)[1]
    assert v1.rejection is None
    v2 = fc.run(model, "S0-A-v2", 5.0, temperature_c=45.0, tank_levels_m=levels)[1]
    assert v2.rejection is not None and v2.rejection["gate"] == "SG0"
    assert v2.rejection["parameter"] == (
        "pumping_minimum_level[TK-101,45C,reference_fittings,NPSH3=4m,coastal,RVP_9_0,f_d=0.6502]"
    )
    assert v2.rejection["limit"] == pytest.approx(6.8784, abs=1e-4)
