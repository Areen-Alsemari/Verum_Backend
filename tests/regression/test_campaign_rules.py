"""Rules added to the campaign in the second round: windows and tags, replacement, branched family,
receipt switch, audit classes and hold-out.

Most checks work on the plan, the cells and the written configuration without a simulation. The
checks that run the engine use one short episode each.

See D150 to D155.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verum.campaign import runner, switch
from verum.campaign.classes import AuditCells
from verum.campaign.eligibility import lineup_info
from verum.campaign.plan import Block, CampaignConfig, build_plan
from verum.campaign.sampler import NoCandidate
from verum.contracts.paths import config_dir
from verum.hydraulics import HydraulicModel
from verum.lineups import load_lineup_table
from verum.sim import deadleg
from verum.sim.config import load_sim_config
from verum.sim.engine import Engine
from verum.sim.episode import RESTRICTED_TIER, TIER, tier_of
from verum.sim.scenario import load_scenario
from verum.sim.validity import ValidityWindow
from verum.truth import ListSink

CONFIG = CampaignConfig(20261101, 3000)
SIGMAS = 4.0


def within(count: int, trials: int, p: float) -> bool:
    """Whether a count is within four binomial standard deviations of its expectation."""
    return abs(count - trials * p) <= SIGMAS * math.sqrt(trials * p * (1 - p)) + 1.0


def window(kind: str, tags: bool) -> ValidityWindow:
    return ValidityWindow("VW-0001", kind, "E-PB3", 10.0, 20.0, "test", None, None, tags)


def engine_in(model: HydraulicModel, mode: str, **changes: Any) -> Engine:
    scenario = dataclasses.replace(
        load_scenario("S0-A"), initial_mode=mode, duration_s=3.0, healthy_envelope=False, **changes
    )
    return Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(), "EP"
    )


def segment_with(model: HydraulicModel, mode: str, edge: str) -> tuple[str, ...]:
    """The edges of the dead segment that holds ``edge`` in a lineup, joined as the solver joins."""
    info = lineup_info(mode)
    dead = [e for e in model.topology.edges if e.edge_id not in info.edges]
    for seg in deadleg._segments(model, dead, info.open_valves):
        if edge in {e.edge_id for e in seg}:
            return tuple(e.edge_id for e in seg)
    raise AssertionError(f"{edge} is not in a dead segment of {mode}")


# --- D150: windows and emitted tags ----------
def test_a_dead_leg_window_that_no_tag_reads_keeps_the_tier(model: HydraulicModel) -> None:
    """In the delivery lineup with pump A the idle branch of pump B has a segment with edge E-PB3
    and no tag, so a dead-leg window there has affects_emitted_tags false and leaves the tier; the
    same window with a tag, and every other kind of window, restricts.

    Independent: yes, because the tags are listed by hand from the sensor contract.
    """
    seg = segment_with(model, "DELIVER_101_A", "E-PB3")
    assert "E-PB2" not in seg  # the tag PT-202B reads E-PB2, in another segment
    engine = engine_in(model, "DELIVER_101_A")
    assert engine._affects_emitted_tags("dead_leg_unvalidated", seg, 0.0) is False
    quiet = SimpleNamespace(windows=[window("dead_leg_unvalidated", False)])
    assert tier_of(quiet) == TIER  # type: ignore[arg-type]
    loud = SimpleNamespace(windows=[window("dead_leg_unvalidated", True)])
    assert tier_of(loud) == RESTRICTED_TIER  # type: ignore[arg-type]
    for kind in ("flow_collapse", "valve_stroke", "path_closed", "branched_lineup"):
        other = SimpleNamespace(windows=[window(kind, False)])
        assert tier_of(other) == RESTRICTED_TIER, kind  # type: ignore[arg-type]
    mixed = SimpleNamespace(
        windows=[window("dead_leg_unvalidated", False), window("flow_collapse", True)]
    )
    assert tier_of(mixed) == RESTRICTED_TIER  # type: ignore[arg-type]


def test_pt_202b_and_the_receipt_header_inside_an_isolated_segment_restrict(
    model: HydraulicModel,
) -> None:
    """The segment of E-PB2 (PT-202B), the segment of E-PA2 (PT-202A) and the receipt header with
    E001 and E002 (FT-001, PT-001) restrict when they are isolated, and the window row carries the
    field.

    Independent: yes, because the tag to edge pairs are listed by hand from the sensor contract.
    """
    engine = engine_in(model, "DELIVER_101_A")
    for mode, edge in (("DELIVER_101_A", "E-PB2"), ("DELIVER_101_B", "E-PA2")):
        seg = segment_with(model, mode, edge)
        assert edge in seg
        assert engine._affects_emitted_tags("dead_leg_unvalidated", seg, 0.0) is True, (mode, seg)
    header = segment_with(model, "DELIVER_101_A", "E001")
    assert {"E001", "E002"} <= set(header)
    assert engine._affects_emitted_tags("dead_leg_unvalidated", header, 0.0) is True
    assert window("flow_collapse", True).as_row()["affects_emitted_tags"] is True


def test_closing_the_receipt_header_gives_a_restricting_dead_leg_window(
    model: HydraulicModel,
) -> None:
    """Closing the common receipt valve cuts off a segment that holds FT-001 and PT-001: the engine
    opens a dead-leg window on it with affects_emitted_tags true, and the episode is restricted.

    Independent: yes, because the segment and the tags are read from the written window row.
    """
    scenario = dataclasses.replace(
        load_scenario("S0-B"), duration_s=500.0, healthy_envelope=False,
        receipt_flow_m3h=300.0, receipt_setpoint_m3h=300.0,
        schedule=[{"t_s": 100.0, "command": "close_valves", "valves": ["XV-R000"]}],
    )  # fmt: skip
    engine = Engine(
        model, load_lineup_table(model.topology), scenario, load_sim_config(), ListSink(), "EP"
    )
    outcome = engine.run()
    dead = [w for w in outcome.windows if w.kind == "dead_leg_unvalidated"]
    assert dead and all(w.affects_emitted_tags for w in dead)
    assert tier_of(outcome) == RESTRICTED_TIER
    rows: Any = engine.sink.rows["validity_windows"]  # type: ignore[attr-defined]
    assert rows and all(isinstance(r["affects_emitted_tags"], bool) for r in rows)


# --- D151: replacement ----------
def fake_attempt(rate: dict[str, float]) -> Any:
    """An attempt that fails with a probability that depends on the family of the cell."""
    import numpy as np

    def run(config: CampaignConfig, slot: Any, attempt: int, layout: Any) -> tuple[Any, Any]:
        cell = runner.context(config).sampler.cell(slot)
        draw = np.random.default_rng([config.seed, slot.index, attempt]).random()
        summary = {"attempt": attempt, "episode_index": slot.index * 5 + attempt}
        if draw < rate.get(cell.family, 0.0):
            return summary | {"status": "excluded", "reason": "validity_window",
                              "windows": ["flow_collapse"]}, None  # fmt: skip
        return summary | {"status": "completed"}, {"episode_id": f"EP-{slot.index:012X}"}

    return run


def test_replacement_keeps_the_cell_shares_and_records_the_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With a failure rate of 0.5 in one family and 0.1 elsewhere, every slot ends completed or in
    a gap after five failures, the completed share of each family is 1 - p^5 within binomial
    bounds, the attempts are numbered from the slot, and the cell table counts them.

    Independent: yes, because the expected shares are arithmetic on the failure rates.
    """
    rate = {"delivery": 0.5}
    monkeypatch.setattr(
        runner, "run_attempt", fake_attempt({**rate, "receipt": 0.1, "concurrent": 0.1})
    )
    config = CampaignConfig(3, 1000)
    records = [runner.execute_slot(config, i, tmp_path) for i in range(config.n)]
    assert all(r["status"] in {"completed", "gap"} for r in records)
    for r in records:
        failed = [a for a in r["attempts"] if a["status"] != "completed"]
        assert [a["attempt"] for a in r["attempts"]] == list(range(len(r["attempts"])))
        assert (r["status"] == "gap") == (len(failed) == 5 and len(r["attempts"]) == 5)
        assert all(a["episode_index"] == r["index"] * 5 + a["attempt"] for a in r["attempts"])
    by_family: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_family.setdefault(r["unit"][0], []).append(r)
    for family, rows in by_family.items():
        p = rate.get(family, 0.1 if family in ("receipt", "concurrent") else 0.0)
        done = sum(r["status"] == "completed" for r in rows)
        assert within(done, len(rows), 1.0 - p**5), family
    table = runner.cell_table(records)
    assert sum(c["attempts"] for c in table.values()) == sum(len(r["attempts"]) for r in records)
    assert sum(c["completed"] + c["gaps"] for c in table.values()) == config.n
    assert sum(sum(c["excluded"].values()) for c in table.values()) > 0


def test_a_replacement_stays_in_the_cell_of_its_slot() -> None:
    """The cell of a slot is the same for every attempt, and the attempts differ in their seed and
    in what they draw inside the cell.

    Independent: yes, because the check compares the attempts of one slot with each other.
    """
    config = CampaignConfig(5, 200)
    ctx = runner.context(config)
    seen = 0
    for slot in ctx.plan[:80]:
        specs = []
        for attempt in range(5):
            try:
                specs.append(ctx.sampler.sample(slot, attempt))
            except NoCandidate:
                continue
        if len(specs) < 2:
            continue
        seen += 1
        assert len({s.cell for s in specs}) == 1
        assert len({s.seed for s in specs}) == len(specs)
        assert all(s.index == slot.index * 5 + s.attempt for s in specs)
        assert len({json.dumps(s.scenario["initial"], sort_keys=True) for s in specs}) > 1
    assert seen > 40


def test_extending_the_target_appends_slots_and_leaves_finished_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A campaign of 120 slots extended to 240 keeps the finished records, byte for byte, and its
    manifest lists the first 120 slots as before.

    Independent: yes, because the first run is the reference for the second.
    """
    monkeypatch.setattr(runner, "execute_slot", runner.execute_slot)
    first = CampaignConfig(9, 120, Block(size=40, healthy=8, single=22, pair=6, branched=4,
                                         latent=1, switch=3, stress=3, audit=4))  # fmt: skip
    longer = dataclasses.replace(first, n=240)
    runner.run_campaign(first, tmp_path, workers=1, executor=_stub)
    layout = runner.Layout(tmp_path)
    before = {p.name: p.read_bytes() for p in layout.records.glob("*.json")}
    stamp = (layout.records / "000050.json").stat().st_mtime_ns
    manifest = runner.run_campaign(longer, tmp_path, workers=1, executor=_stub)
    assert (layout.records / "000050.json").stat().st_mtime_ns == stamp
    assert all((layout.records / name).read_bytes() == data for name, data in before.items())
    assert len(manifest["episodes"]) == 240 and manifest["target_n"] == 240
    assert build_plan(longer)[:120] == build_plan(first)


def _stub(config: CampaignConfig, index: int, root: Path) -> dict[str, Any]:
    record = runner.slot_record(config, runner.context(config).plan[index])
    return {**record, "status": "gap", "wall_s": 0.0, "attempts": [
        {"attempt": 0, "episode_index": index * 5, "status": "rejected", "gate": "SAMPLING"}
    ]}  # fmt: skip


# --- D152: branched family ----------
def test_the_branched_family_is_at_most_six_percent_and_has_its_own_stratum() -> None:
    """The branched slots are 6 percent of the plan, their cells are in the family branched, their
    lineup is the receipt into two tanks unless a misrouting (a) opens a second suction or receipt
    branch, and no other family contains a branched slot.

    Independent: yes, because the share is the block composition and the valves are named by hand.
    """
    ctx = runner.context(CONFIG)
    branched = [s for s in ctx.plan if s.kind == "branched"]
    assert len(branched) == 0.06 * CONFIG.n
    for slot in branched:
        cell = ctx.sampler.cell(slot)
        assert cell.family == "branched"
        try:
            spec = ctx.sampler.sample(slot, 0)
        except NoCandidate:
            continue
        mode = spec.strata["mode"]
        if slot.branch in ("healthy", "misroute_b"):
            assert mode == "RECEIVE_101_102"
        else:
            info = lineup_info(mode)
            asset = spec.faults[0].asset
            assert asset not in info.open_valves
            assert asset.startswith("XV-S" if mode.startswith("DELIVER") else "XV-R1")
    assert all(ctx.sampler.cell(s).family != "branched" for s in ctx.plan if s.kind != "branched")
    assert any(u[0] == "branched" for u in ctx.splits.unit_shares)
    assert not any(u[0] == "branched" for u in ctx.splits.test_units)


@pytest.mark.slow
def test_a_branched_episode_is_completed_with_the_restricted_tier(tmp_path: Path) -> None:
    """A healthy branched slot is completed, not excluded for its window, and its tier is
    restricted_benchmark with a branched-lineup window in the hidden records.

    Independent: yes, because the tier is read from the stored episode and the window kind from
    the stored window records.
    """
    import gzip

    config = CampaignConfig(31, 20, Block(size=20, healthy=2, single=2, pair=2, branched=14,
                                          latent=0, switch=0, stress=0, audit=0))  # fmt: skip
    slot = next(s for s in runner.context(config).plan if s.branch == "healthy")
    record = runner.execute_slot(config, slot.index, tmp_path)
    assert record["status"] == "completed" and record["tier"] == "restricted_benchmark"
    layout = runner.Layout(tmp_path)
    path = layout.evaluator / "episodes" / record["episode_id"] / "validity_windows.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        kinds = {json.loads(line)["kind"] for line in handle}
    assert kinds == {"branched_lineup"}


# --- D153: receipt switch ----------
def test_the_switch_table_agrees_with_hand_arithmetic() -> None:
    """The round trips of the receipt paths are 0.3609, 0.4251 and 0.4894 s, the criterion is ten
    times that, a single step falls in 2 ln 9 = 4.394 s, the two-stage fall from 400 and 600 is
    7.10 and 7.03 s, the flow at the end of the stroke is 42.4 and 46.1 m3/h against 60, and only
    the third tank at 300 m3/h keeps a collapse window.

    Independent: yes, because every number is worked out by hand from the controller constant of
    2 s, the stage values and the round trips of the path lengths and wave speeds.
    """
    rows = switch.table((300.0, 400.0, 500.0, 600.0))
    trips = {r["tank"]: r["round_trip_s"] for r in rows}
    assert trips == pytest.approx(
        {"TK-101": 0.36087, "TK-102": 0.42514, "TK-103": 0.48941}, rel=1e-4
    )
    assert all(r["criterion_s"] == pytest.approx(10 * r["round_trip_s"]) for r in rows)
    pick = {(r["tank"], r["setpoint_m3h"]): r for r in rows}
    assert pick["TK-101", 300.0]["fall_s"] == pytest.approx(2 * math.log(9), rel=1e-12)
    t90 = -2 * math.log((0.9 * 400 - 300) / (400 - 300))
    t10 = 4 + 2 * math.log((300 + 100 * math.exp(-2)) / 40)
    assert pick["TK-101", 400.0]["fall_s"] == pytest.approx(t10 - t90, rel=1e-9)
    assert pick["TK-101", 400.0]["fall_s"] == pytest.approx(7.10, abs=0.01)
    assert pick["TK-101", 600.0]["fall_s"] == pytest.approx(7.03, abs=0.01)
    assert pick["TK-101", 400.0]["closing_flow_m3h"] == pytest.approx(42.4, abs=0.1)
    assert pick["TK-101", 600.0]["closing_flow_m3h"] == pytest.approx(
        (300 + 300 * math.exp(-2)) * math.exp(-2), rel=1e-12
    )
    windows = {(t, sp) for (t, sp), r in pick.items() if r["collapse_window"]}
    assert windows == {("TK-103", 300.0)}
    assert not any(r["stroke_window"] for r in rows)
    assert switch.setpoints_for("TK-103", (300.0, 400.0)) == (400.0,)
    assert switch.setpoints_for("TK-101", (300.0, 400.0)) == (300.0, 400.0)


def test_a_switch_slot_never_draws_the_combination_that_keeps_a_window() -> None:
    """In 3000 slots no switch episode starts on TK-103 at 300 m3/h, the schedule has two stages
    above 300 and one step at 300, and the manifest records the left-out combination.

    Independent: yes, because the rule is applied to the sampled schedules by direct reading.
    """
    ctx = runner.context(CONFIG)
    seen: Counter[tuple[str, float]] = Counter()
    for slot in ctx.plan:
        if not slot.switch:
            continue
        try:
            spec = ctx.sampler.sample(slot, 0)
        except NoCandidate:
            continue
        first, sp = spec.strata["mode"][-3:], spec.strata["setpoint_m3h"]
        seen[first, sp] += 1
        assert not (first == "103" and sp == 300.0)
        steps = [s for s in spec.scenario["schedule"] if s["command"] == "receipt_setpoint"]
        assert [s["value_m3h"] for s in steps][:-1] == (
            [sp, 300.0, 0.0] if sp > 300.0 else [sp, 0.0]
        )
    assert seen and any(sp == 300.0 for _, sp in seen)
    assert runner.switch_gaps() == [
        {
            "subtype": "switch", "first_tank": "TK-103", "setpoint_m3h": 300.0,
            "reason": runner.switch_gaps()[0]["reason"],
        }
    ]  # fmt: skip


@pytest.mark.slow
def test_the_two_stage_ramp_gives_no_collapse_window_for_the_tanks_of_the_table() -> None:
    """A switch from each receiving tank, with the two-stage ramp from 400 and 600 m3/h, gives no
    window of the receipt path, and the single step from the third tank at 300 m3/h gives a flow
    collapse of 4.4 s against the criterion of 4.89 s.

    Independent: yes, because the windows are produced by the engine and the numbers they are
    compared with are the table of hand arithmetic.
    """
    import tempfile

    from verum.campaign.eligibility import model_and_table
    from verum.sim.episode import run_episode
    from verum.sim.scenario import parse_scenario

    model, _ = model_and_table()

    def run(first: str, second: str, setpoint: float) -> list[ValidityWindow]:
        raw: dict[str, Any] = {
            "scenario_id": f"SW{first}{int(setpoint)}", "description": "switch", "seed": 7,
            "duration_s": 2000.0, "temperature_c": 25.0, "fitting_profile": "reference_fittings",
            "healthy_envelope": True, "atmosphere_stratum": "coastal",
            "volatility_class": "RVP_9_0", "demand_process": True, "variability_profile": "v2",
            "initial": {"mode": f"RECEIVE_{first}", "receipt_flow_m3h": 0.0,
                        "receipt_setpoint_m3h": 0.0,
                        "tank_levels_m": {"TK-101": 4.0, "TK-102": 4.0, "TK-103": 4.0}},
            "schedule": switch.schedule(f"RECEIVE_{first}", f"RECEIVE_{second}", setpoint),
        }  # fmt: skip
        with tempfile.TemporaryDirectory() as d:
            result = run_episode(raw["scenario_id"], Path(d), model, parse_scenario(raw), None)
            assert not result.rejected
            return list(result.outcome.windows)

    for first, second, sp in (("101", "102", 600.0), ("102", "103", 500.0), ("103", "101", 400.0)):
        assert run(first, second, sp) == [], (first, sp)
    single = run("103", "101", 300.0)
    assert [w.kind for w in single] == ["flow_collapse"]
    end = single[0].t_end_s
    assert end is not None
    assert end - single[0].t_start_s == pytest.approx(2 * math.log(9), abs=0.05)
    assert single[0].round_trip_s == pytest.approx(0.48941, rel=1e-4)


# --- D154: classes of stuck-at and misrouting (a) ----------
def test_the_audit_cells_follow_the_margin_rule() -> None:
    """Each stored cell is invisible below a margin of 1, marginal below 3 and clear from 3, the
    cell of misrouting (a) of XV-PBO in the lineup with a receipt and a delivery was rejected and
    reads unaudited, and a lineup that was not audited reads unaudited.

    Independent: yes, because the class is recomputed from the stored margin by the rule of D89.
    """
    raw = json.loads((config_dir() / "audit_cells.json").read_text(encoding="utf-8"))
    cells = AuditCells()
    assert raw["cells"]
    for key, cell in raw["cells"].items():
        want = "invisible" if cell["margin"] < 1 else "marginal" if cell["margin"] < 3 else "clear"
        subtype, mode, asset = key.split("/")
        assert cells.class_of(subtype, mode, asset) == want, key
    assert cells.class_of("misroute_a", "RECEIVE_101_DELIVER_102_A", "XV-PBO") == "unaudited"
    assert "misroute_a/RECEIVE_101_DELIVER_102_A/XV-PBO" in raw["rejected"]
    assert cells.class_of("stuck", "DELIVER_103_B", "FT-201") == "unaudited"
    assert cells.class_of("stuck", "RECEIVE_101", "PT-001") == "invisible"
    assert cells.class_of("misroute_a", "DELIVER_101_A", "XV-S102") == "clear"


def test_sampled_stuck_and_misrouting_faults_take_their_class_from_the_audit_cell() -> None:
    """Over 3000 slots every active stuck-at and misrouting (a) has the class of the audit cell of
    its lineup and asset, a latent one is latent, and both audited classes and the class
    unaudited occur.

    Independent: yes, because the expected class is read from the stored cell by lineup and asset.
    """
    ctx = runner.context(CONFIG)
    audit = AuditCells()
    seen: Counter[str] = Counter()
    for slot in ctx.plan:
        if slot.kind == "branched":
            continue
        try:
            spec = ctx.sampler.sample(slot, 0)
        except NoCandidate:
            continue
        mode = [s["mode"] for s in spec.scenario["schedule"] if s["command"] == "lineup"][-1:]
        mode = mode or [spec.scenario["initial"]["mode"]]
        for f in spec.faults:
            if f.subtype not in ("stuck", "misroute_a"):
                continue
            want = "latent" if slot.latent else audit.class_of(f.subtype, mode[-1], f.asset)
            assert f.cls == want, (slot.index, f.subtype, f.asset, mode)
            seen[f.cls] += 1
    assert seen["unaudited"] > 0 and seen["invisible"] + seen["marginal"] + seen["clear"] > 0
    assert set(seen) <= {"invisible", "marginal", "clear", "unaudited", "latent"}


# --- D155: hold-out ----------
def test_held_out_units_and_asset_pairs_follow_the_rule() -> None:
    """Held-out units each hold at least 2.5 percent of the plan and together at least 8 percent,
    a subtype with fewer than four assets (the pumps and misrouting (b)) holds out an asset and
    family pair, the others an asset, and a pair episode is test if either fault is held out.

    Independent: yes, because the shares are counted from the cells and the pair rule is applied
    to constructed faults.
    """
    from verum.campaign.splits import asset_pool, split_of

    splits = runner.context(CONFIG).splits
    assert all(splits.unit_shares[u] >= 0.025 for u in splits.test_units)
    assert sum(splits.unit_shares[u] for u in splits.test_units) >= 0.08
    for subtype, (asset, family) in splits.held_assets.items():
        pool = asset_pool(subtype)
        assert asset in pool
        assert (family is None) == (len(pool) >= 4), subtype
    assert splits.held_assets["pump"][1] in ("delivery", "concurrent")
    assert splits.held_assets["misroute_b"][1] == "branched"
    free = next(
        u for u in splits.unit_shares if u not in splits.test_units | splits.validation_units
    )
    leak_asset = splits.held_assets["leak"][0]
    other = next(a for a in asset_pool("leak") if a != leak_asset)
    assert split_of(splits, free, [("leak", other), ("bias", "FT-001")]) in (
        "train",
        "validation",
    ) or (splits.held_assets["bias"][0] == "FT-001")
    assert split_of(splits, free, [("leak", other), ("leak", leak_asset)]) == "test"
    pump, family = splits.held_assets["pump"]
    elsewhere = (next(f for f in ("delivery", "concurrent") if f != family), free[1], free[2])
    assert split_of(splits, elsewhere, [("pump", pump)]) in ("train", "validation")
