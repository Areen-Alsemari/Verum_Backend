"""Protection state machine: trip, isolation, availability, reset and the absence of handles.

Injected signal sequences drive the machine, with levels, closure evidence and flows written
directly into the tests and no hydraulics. The isolation timeout for tank TK-101 is the slowest
requested valve, 2 x 30 s + 1.5 s = 61.5 s, where the common valve alone would give 22 s. The
residual-flow threshold is 1.0 m3/h, and the machine takes one transition per update.

See D12 and D13.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

import verum.protection.machine as machine_module
from verum.contracts import ContractError, Topology
from verum.lineups import LineupTable, load_lineup_table
from verum.params import UnresolvedParameter
from verum.protection import (
    AuthorisedReset,
    ProtectionState,
    ReceiptBlocked,
    ResetRefused,
    Signals,
    TankProtection,
    assert_receipt_allowed,
    load_protection_config,
)
from verum.protection.config import parse_protection_config

S = ProtectionState
CLOSED = {"XV-R000": True, "XV-R101": True}
TIMEOUT = 61.5


@pytest.fixture
def prot(topology: Topology) -> TankProtection:
    return TankProtection(load_protection_config(topology, "TK-101"))


@pytest.fixture(scope="module")
def table(topology: Topology) -> LineupTable:
    return load_lineup_table(topology)


def now(p: TankProtection) -> ProtectionState:
    """Current state, typed widely so later comparisons are not narrowed."""
    return p.state


def sig(t: float, lt: float | None = 10.0, ind: float | None = 10.0, **kw: Any) -> Signals:
    return Signals(t_s=t, process_level_m=lt, independent_level_m=ind, **kw)


def trip(p: TankProtection, t: float = 100.0) -> None:
    p.update(sig(t, lt=12.0, ind=13.0))
    assert p.state is S.HIGH_HIGH


# --- configuration -------------------------------------------------------------------


def test_timing_comes_from_provisional_parameter_records(topology: Topology) -> None:
    """The timeout multiplier and the residual-flow threshold are provisional simulation parameters.
    Independent: yes, because the expected status is the stated rule.
    """
    cfg = load_protection_config(topology, "TK-101")
    for record in (cfg.timeout_multiplier, cfg.residual_flow_m3h):
        assert (record.status, record.evidence_tag) == ("provisional", "SIM")
        assert record.provenance_id
    assert cfg.timeout_multiplier.value == 2.0
    assert cfg.residual_flow_threshold_m3h == 1.0


def test_timeouts_are_two_strokes_plus_lag(topology: Topology) -> None:
    """The valve timeouts are twice the stroke time plus the contact lag, 22 s for the common
    receipt valve and 61.5 s for the tank inlet valve. Independent: yes, because the values are hand
    arithmetic.
    """
    cfg = load_protection_config(topology, "TK-101")
    assert cfg.valve_timeout_s("XV-R000") == 22.0
    assert cfg.valve_timeout_s("XV-R101") == 61.5
    assert cfg.timeout_s() == TIMEOUT
    assert cfg.isolation_valves == ("XV-R000", "XV-R101")


@pytest.mark.parametrize("tank", ["TK-101", "TK-102", "TK-103"])
def test_every_tank_has_a_configuration(topology: Topology, tank: str) -> None:
    """Every tank has a protection configuration with the alarm and high-high levels and its two
    isolation valves. Independent: yes, because the expected values are the contract thresholds.
    """
    cfg = load_protection_config(topology, tank)
    assert (cfg.high_alarm_m, cfg.high_high_m) == (12.5, 13)
    assert cfg.isolation_valves == ("XV-R000", f"XV-R{tank[3:]}")
    assert cfg.timeout_s() == TIMEOUT


def test_unknown_tank_is_rejected(topology: Topology) -> None:
    """A protection configuration for an unknown tank is rejected. Independent: yes, because the
    expected outcome is the validation rule.
    """
    with pytest.raises(ContractError):
        load_protection_config(topology, "TK-999")


@pytest.mark.parametrize(
    "name", ["isolation_timeout_stroke_multiplier", "residual_flow_threshold_m3h"]
)
def test_an_unresolved_parameter_stops_start_up(topology: Topology, name: str, root: Path) -> None:
    """An unresolved protection parameter stops start-up. Independent: yes, because the expected
    outcome is the rule that nothing replaces an unresolved parameter.
    """
    raw = json.loads((root / "config" / "protection.json").read_text(encoding="utf-8"))
    raw["parameters"][name] = {
        "value": None,
        "unit": "1",
        "status": "unresolved",
        "evidence_tag": "OPEN",
        "unresolved_reason": "not selected",
    }
    with pytest.raises(UnresolvedParameter):
        TankProtection(parse_protection_config(raw, topology.tanks[0]))


def test_an_unresolved_stroke_time_stops_start_up(topology: Topology, root: Path) -> None:
    """An unresolved valve stroke time stops start-up. Independent: yes, because the expected
    outcome is the same rule.
    """
    raw = json.loads((root / "config" / "protection.json").read_text(encoding="utf-8"))
    raw["parameters"]["stroke_time_s"]["XV-R101"] = {
        "value": None,
        "unit": "s",
        "status": "unresolved",
        "evidence_tag": "OPEN",
    }
    with pytest.raises(UnresolvedParameter):
        TankProtection(parse_protection_config(raw, topology.tanks[0]))


def test_a_missing_valve_entry_is_a_contract_error(topology: Topology, root: Path) -> None:
    """A missing valve entry in the configuration is a contract error. Independent: yes, because the
    expected outcome is the validation rule.
    """
    raw = json.loads((root / "config" / "protection.json").read_text(encoding="utf-8"))
    del raw["parameters"]["contact_lag_s"]["XV-R101"]
    with pytest.raises(ContractError):
        TankProtection(parse_protection_config(raw, topology.tanks[0]))


# --- trip ------------------------------------------------------------------------------


def test_starts_normal_and_unlatched(prot: TankProtection) -> None:
    """A new machine is in the normal state, not latched, and permits receipt. Independent: yes,
    because the expected state is the stated initial state.
    """
    assert prot.state is S.NORMAL
    assert not prot.trip_latched
    assert prot.normal_receipt_permitted


def test_high_high_trips_on_the_independent_signal_when_lt_drifts_low(prot: TankProtection) -> None:
    """The machine trips on the independent signal even when the process level reads a metre low.
    Independent: yes, because the expected outcome is the rule that the trip uses the independent
    signal.
    """
    prot.update(sig(0, lt=11.0, ind=11.0))
    prot.update(sig(1, lt=12.0, ind=13.05))  # LT reads a metre low
    assert prot.state is S.HIGH_HIGH
    assert prot.trip_latched
    assert [e.kind for e in prot.events] == ["HIGH_HIGH_TRIP"]


def test_trip_is_direct_from_normal_and_skips_the_high_alarm(prot: TankProtection) -> None:
    """A trip is possible directly from the normal state without passing the high alarm.
    Independent: yes, because the expected outcome is the transition rule.
    """
    prot.update(sig(0, lt=12.4, ind=12.4))
    prot.update(sig(1, lt=12.4, ind=13.0))
    assert prot.state is S.HIGH_HIGH
    assert "HIGH_ALARM" not in [e.kind for e in prot.events]


def test_trip_level_is_inclusive_and_just_below_does_not_trip(prot: TankProtection) -> None:
    """A level of 13.0 m trips and 12.999 m does not. Independent: yes, because the threshold is the
    stated value.
    """
    prot.update(sig(0, ind=12.999))
    assert prot.state is S.NORMAL
    prot.update(sig(1, ind=13.0))
    assert now(prot) is S.HIGH_HIGH


def test_a_high_lt_alone_gives_an_alarm_and_never_a_trip(prot: TankProtection) -> None:
    """A high process level alone gives the high alarm and never a trip. Independent: yes, because
    the expected outcome is the rule that the process level cannot trip.
    """
    prot.update(sig(0, lt=13.5, ind=12.0))
    assert prot.state is S.HIGH_ALARM
    assert not prot.trip_latched
    assert prot.normal_receipt_permitted


def test_high_alarm_starts_at_12_5_and_clears_below(prot: TankProtection) -> None:
    """The high alarm starts at 12.5 m and clears below the level less the hysteresis. Independent:
    yes, because the thresholds are the stated values.
    """
    prot.update(sig(0, lt=12.49))
    assert prot.state is S.NORMAL
    prot.update(sig(1, lt=12.5))
    assert now(prot) is S.HIGH_ALARM
    prot.update(sig(2, lt=12.0))
    assert prot.state is S.NORMAL
    assert [e.kind for e in prot.events] == ["HIGH_ALARM", "ALARM_CLEARED"]


def test_the_alarm_does_not_inhibit_the_trip(prot: TankProtection) -> None:
    """A standing high alarm does not prevent a trip. Independent: yes, because the expected outcome
    is the transition rule.
    """
    prot.update(sig(0, lt=12.6, ind=12.6))
    prot.update(sig(1, lt=12.6, ind=13.1))
    assert prot.state is S.HIGH_HIGH


def test_a_missing_independent_reading_never_trips(prot: TankProtection) -> None:
    """A missing independent reading never trips, and the alarm remains. Independent: yes, because
    the expected outcome is the rule that nothing is invented.
    """
    prot.update(sig(0, lt=14.0, ind=None))
    assert prot.state is S.HIGH_ALARM


# --- isolation -------------------------------------------------------------------------


def test_next_update_requests_isolation_without_confirming(prot: TankProtection) -> None:
    """The update after a trip requests isolation without confirming it. Independent: yes, because
    the expected outcome is the one-transition-per-update rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2, receipt_flow_m3h=600.0))
    assert prot.state is S.ISOLATION_REQUESTED
    event = prot.events[-1]
    assert event.kind == "ISOLATION_REQUESTED"
    assert event.requested_valves == ("XV-R000", "XV-R101")
    assert "not confirmed" in event.detail


def test_request_without_closure_never_reaches_confirmed(prot: TankProtection) -> None:
    """A request without closure evidence never reaches the confirmed state. Independent: yes,
    because the expected outcome is the rule that a request is not a closure.
    """
    trip(prot)
    seen = set()
    for i in range(1, 400):
        prot.update(sig(100 + i, ind=13.2, receipt_flow_m3h=0.0))
        seen.add(prot.state)
    assert S.CONFIRMED_ISOLATED not in seen
    assert prot.state is S.FAILED_ISOLATION
    assert "without closure evidence" in prot.events[-1].detail


def test_closure_evidence_with_flow_stop_confirms_before_the_timeout(prot: TankProtection) -> None:
    """Closure evidence for both valves together with a receipt flow at or below the threshold
    confirms isolation before the timeout. Independent: yes, because the expected outcome is the
    confirmation rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2, receipt_flow_m3h=600.0))
    prot.update(sig(120, ind=13.2, receipt_flow_m3h=0.2, closed_confirmed=CLOSED))
    assert prot.state is S.CONFIRMED_ISOLATED
    assert prot.trip_latched
    assert prot.events[-1].kind == "ISOLATION_CONFIRMED"


def test_closure_without_flow_stop_does_not_confirm(prot: TankProtection) -> None:
    """Closure evidence with a receipt flow above the threshold does not confirm isolation.
    Independent: yes, because the expected outcome is the confirmation rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(120, ind=13.2, receipt_flow_m3h=50.0, closed_confirmed=CLOSED))
    assert prot.state is S.ISOLATION_REQUESTED


def test_only_one_valve_closed_does_not_confirm(prot: TankProtection) -> None:
    """Closure of only one of the two valves does not confirm isolation. Independent: yes, because
    the expected outcome is the confirmation rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(120, ind=13.2, receipt_flow_m3h=0.0, closed_confirmed={"XV-R000": True}))
    assert prot.state is S.ISOLATION_REQUESTED


def test_the_flow_threshold_is_inclusive(topology: Topology) -> None:
    """A residual flow equal to the threshold confirms isolation and a flow just above it does not.
    Independent: yes, because the threshold is the stated value.
    """
    at, above = (TankProtection(load_protection_config(topology, "TK-101")) for _ in range(2))
    for p, flow, expected in (
        (at, 1.0, S.CONFIRMED_ISOLATED),
        (above, 1.0001, S.ISOLATION_REQUESTED),
    ):
        trip(p)
        p.update(sig(101, ind=13.2))
        p.update(sig(110, ind=13.2, receipt_flow_m3h=flow, closed_confirmed=CLOSED))
        assert p.state is expected


def test_residual_flow_after_the_timeout_fails_isolation(prot: TankProtection) -> None:
    """A residual flow above the threshold at the timeout fails the isolation. Independent: yes,
    because the expected outcome is the timeout rule.
    """
    trip(prot, t=100.0)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(100 + TIMEOUT - 1, ind=13.2, receipt_flow_m3h=5.0, closed_confirmed=CLOSED))
    assert prot.state is S.ISOLATION_REQUESTED  # flow is allowed while the valves travel
    prot.update(sig(100 + TIMEOUT, ind=13.2, receipt_flow_m3h=5.0, closed_confirmed=CLOSED))
    assert now(prot) is S.FAILED_ISOLATION
    assert "residual flow" in prot.events[-1].detail


def test_timeout_without_flow_evidence_fails(prot: TankProtection) -> None:
    """A timeout with no flow evidence fails the isolation. Independent: yes, because the expected
    outcome is the timeout rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(100 + TIMEOUT, ind=13.2, closed_confirmed=CLOSED, receipt_flow_m3h=None))
    assert prot.state is S.FAILED_ISOLATION
    assert "without flow evidence" in prot.events[-1].detail


def test_withdrawn_closure_evidence_is_a_contradiction(prot: TankProtection) -> None:
    """Closure evidence that is withdrawn after being given is treated as a contradiction.
    Independent: yes, because the expected outcome is the evidence rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(105, ind=13.2, receipt_flow_m3h=100.0, closed_confirmed={"XV-R000": True}))
    prot.update(sig(110, ind=13.2, receipt_flow_m3h=100.0, closed_confirmed={"XV-R000": False}))
    assert prot.state is S.FAILED_ISOLATION
    assert "contradiction" in prot.events[-1].detail


def test_evidence_withdrawn_after_confirmation_fails(prot: TankProtection) -> None:
    """Evidence that is withdrawn after confirmation fails the isolation. Independent: yes, because
    the expected outcome is the evidence rule.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    prot.update(sig(110, ind=13.2, receipt_flow_m3h=0.0, closed_confirmed=CLOSED))
    assert prot.state is S.CONFIRMED_ISOLATED
    prot.update(sig(111, ind=13.2, receipt_flow_m3h=0.0, closed_confirmed={"XV-R000": True}))
    assert now(prot) is S.FAILED_ISOLATION


def test_failed_isolation_is_latched_and_does_not_divert(prot: TankProtection) -> None:
    """A failed isolation stays latched and does not divert to another state. Independent: yes,
    because the expected outcome is the latch rule.
    """
    trip(prot)
    for i in range(1, 200):
        prot.update(sig(100 + i, ind=13.2, receipt_flow_m3h=0.0, closed_confirmed=None))
    assert prot.state is S.FAILED_ISOLATION
    prot.update(sig(400, ind=10.0, receipt_flow_m3h=0.0, closed_confirmed=CLOSED))
    assert prot.state is S.FAILED_ISOLATION
    assert all(not e.requested_valves or e.kind == "ISOLATION_REQUESTED" for e in prot.events)


def test_the_timeout_runs_from_the_trip_time(prot: TankProtection) -> None:
    """The timeout counts from the trip time and not from the request. Independent: yes, because the
    expected outcome is the timeout rule.
    """
    trip(prot, t=1000.0)
    prot.update(sig(1000.0 + TIMEOUT - 0.5, ind=13.2))
    assert prot.state is S.ISOLATION_REQUESTED
    prot.update(sig(1000.0 + TIMEOUT, ind=13.2))
    assert now(prot) is S.FAILED_ISOLATION


# --- availability ----------------------------------------------------------------------


@pytest.mark.parametrize("kw", [{"independent_valid": False}, {"power_ok": False}])
def test_unavailable_protection_blocks_normal_receipt(
    prot: TankProtection, table: LineupTable, kw: dict[str, bool]
) -> None:
    """A protection that is unavailable because of an invalid signal or lost power blocks normal
    receipt. Independent: yes, because the expected outcome is the availability rule.
    """
    prot.update(sig(0, **kw))
    assert prot.state is S.PROTECTION_UNAVAILABLE
    assert not prot.normal_receipt_permitted
    with pytest.raises(ReceiptBlocked, match="PROTECTION_UNAVAILABLE"):
        assert_receipt_allowed(table.mode("RECEIVE_101"), {"TK-101": prot})
    assert prot.events[-1].kind == "PROTECTION_UNAVAILABLE"


def test_unavailable_protection_does_not_block_delivery_or_other_tanks(
    prot: TankProtection, table: LineupTable, topology: Topology
) -> None:
    """An unavailable protection does not block a delivery or the receipt into another tank.
    Independent: yes, because the expected outcome is the interlock rule.
    """
    prot.update(sig(0, independent_valid=False))
    other = TankProtection(load_protection_config(topology, "TK-102"))
    assert_receipt_allowed(table.mode("DELIVER_101_A"), {"TK-101": prot})
    assert_receipt_allowed(table.mode("RECEIVE_102"), {"TK-101": prot, "TK-102": other})


def test_one_unavailable_tank_blocks_a_two_tank_receipt(
    prot: TankProtection, table: LineupTable, topology: Topology
) -> None:
    """A receipt into two tanks is blocked if either tank's protection is unavailable. Independent:
    yes, because the expected outcome is the interlock rule.
    """
    other = TankProtection(load_protection_config(topology, "TK-102"))
    other.update(sig(0, power_ok=False))
    with pytest.raises(ReceiptBlocked, match="TK-102"):
        assert_receipt_allowed(table.mode("RECEIVE_101_102"), {"TK-101": prot, "TK-102": other})


def test_missing_protection_blocks_receipt(table: LineupTable) -> None:
    """A receipt with no protection machine for its tank is blocked. Independent: yes, because the
    expected outcome is the interlock rule.
    """
    with pytest.raises(ReceiptBlocked, match="no protection"):
        assert_receipt_allowed(table.mode("RECEIVE_101"), {})


def test_a_high_alarm_still_permits_receipt(prot: TankProtection, table: LineupTable) -> None:
    """A receipt into a tank in high alarm is still permitted. Independent: yes, because the
    expected outcome is the interlock rule.
    """
    prot.update(sig(0, lt=12.6))
    assert_receipt_allowed(table.mode("RECEIVE_101"), {"TK-101": prot})


def test_a_latched_trip_blocks_receipt(prot: TankProtection, table: LineupTable) -> None:
    """A latched trip blocks receipt into its tank. Independent: yes, because the expected outcome
    is the interlock rule.
    """
    trip(prot)
    with pytest.raises(ReceiptBlocked):
        assert_receipt_allowed(table.mode("RECEIVE_101"), {"TK-101": prot})


def test_an_invalid_signal_does_not_trip(prot: TankProtection) -> None:
    """An invalid independent signal makes protection unavailable and does not trip. Independent:
    yes, because the expected outcome is the availability rule.
    """
    prot.update(sig(0, ind=13.5, independent_valid=False))
    assert prot.state is S.PROTECTION_UNAVAILABLE
    assert not prot.trip_latched


def test_protection_recovers_to_normal_when_the_signal_returns(prot: TankProtection) -> None:
    """Protection returns to normal when a valid signal returns, if nothing is latched. Independent:
    yes, because the expected outcome is the availability rule.
    """
    prot.update(sig(0, independent_valid=False))
    prot.update(sig(1))
    assert prot.state is S.NORMAL
    assert [e.kind for e in prot.events] == ["PROTECTION_UNAVAILABLE", "PROTECTION_AVAILABLE"]


def test_a_latched_trip_survives_a_later_invalid_signal(prot: TankProtection) -> None:
    """A latched trip and its isolation sequence survive a later invalid signal. Independent: yes,
    because the expected outcome is the latch rule.
    """
    trip(prot)
    prot.update(sig(101, ind=None, independent_valid=False))
    assert prot.state is S.ISOLATION_REQUESTED
    assert prot.trip_latched


# --- latch and reset -------------------------------------------------------------------


def test_a_latched_trip_does_not_clear_when_the_level_falls(prot: TankProtection) -> None:
    """A latched trip does not clear when the level falls. Independent: yes, because the expected
    outcome is the latch rule.
    """
    trip(prot)
    for i in range(1, 50):
        prot.update(sig(100 + i, lt=8.0, ind=8.0, receipt_flow_m3h=0.0, closed_confirmed=CLOSED))
    assert prot.trip_latched
    assert prot.state is S.CONFIRMED_ISOLATED


@pytest.mark.parametrize(
    "source", ["agent", "verum", "advisory", "", "OPERATIONS", "simulator_truth"]
)
def test_reset_from_any_other_source_is_refused(prot: TankProtection, source: str) -> None:
    """A reset from any source other than operations or protection is refused. Independent: yes,
    because the expected outcome is the authorisation rule.
    """
    trip(prot)
    with pytest.raises(ResetRefused, match="not authorised"):
        prot.reset(AuthorisedReset(source, "someone", 200.0), sig(200, ind=8.0))
    assert prot.trip_latched


def test_reset_needs_a_named_authoriser(prot: TankProtection) -> None:
    """A reset with no named authoriser is refused. Independent: yes, because the expected outcome
    is the authorisation rule.
    """
    trip(prot)
    with pytest.raises(ResetRefused):
        prot.reset(AuthorisedReset("operations", "", 200.0), sig(200, ind=8.0))


@pytest.mark.parametrize(
    "signals",
    [
        sig(200, ind=13.0),
        sig(200, ind=14.0),
        sig(200, ind=12.96),
        sig(200, ind=12.95),
        sig(200, ind=None),
        sig(200, ind=8.0, independent_valid=False),
    ],
)
def test_reset_needs_the_safe_predicates(prot: TankProtection, signals: Signals) -> None:
    """A reset is refused unless the independent signal is valid and below the trip level less the
    hysteresis. Independent: yes, because the expected outcome is the reset rule.
    """
    trip(prot)
    with pytest.raises(ResetRefused, match="safe predicates"):
        prot.reset(AuthorisedReset("operations", "shift lead", 200.0), signals)
    assert prot.trip_latched


@pytest.mark.parametrize("source", ["operations", "protection"])
def test_an_authorised_reset_clears_the_latch(prot: TankProtection, source: str) -> None:
    """An authorised reset under safe conditions clears the latch and returns to normal.
    Independent: yes, because the expected outcome is the reset rule.
    """
    trip(prot)
    state = prot.reset(AuthorisedReset(source, "shift lead", 200.0), sig(200, ind=8.0))
    assert state is S.NORMAL and not prot.trip_latched
    assert prot.events[-1].kind == "RESET"
    prot.update(sig(201, ind=13.1))
    assert prot.state is S.HIGH_HIGH


def test_reset_is_allowed_just_below_the_hysteresis_ceiling(prot: TankProtection) -> None:
    """A reset is allowed at a level just below the trip level less the hysteresis. Independent:
    yes, because the ceiling is hand arithmetic.
    """
    trip(prot)
    state = prot.reset(AuthorisedReset("operations", "shift lead", 200.0), sig(200, ind=12.9499))
    assert state is S.NORMAL


def test_reset_without_a_latched_trip_is_refused(prot: TankProtection) -> None:
    """A reset when no trip is latched is refused. Independent: yes, because the expected outcome is
    the reset rule.
    """
    with pytest.raises(ResetRefused, match="no latched trip"):
        prot.reset(AuthorisedReset("operations", "shift lead", 1.0), sig(1))


def test_time_cannot_go_backwards(prot: TankProtection) -> None:
    """An update with an earlier time than the previous one is rejected. Independent: yes, because
    the expected outcome is the validation rule.
    """
    prot.update(sig(10))
    with pytest.raises(ValueError):
        prot.update(sig(9))


# --- no handle for an agent ------------------------------------------------------------

FORBIDDEN = (
    "bypass",
    "override",
    "inhibit",
    "force",
    "actuate",
    "command",
    "open",
    "close",
    "set_",
    "write",
)


def test_public_surface_of_the_state_machine_is_the_expected_set(prot: TankProtection) -> None:
    """The public attributes of the state machine are exactly the expected set. Independent: yes,
    because the set is written out in the test.
    """
    public = {n for n in dir(prot) if not n.startswith("_")}
    assert public == {
        "events",
        "normal_receipt_permitted",
        "reset",
        "state",
        "timeout_s",
        "trip_latched",
        "update",
    }


def test_no_public_callable_suggests_command_or_bypass(prot: TankProtection) -> None:
    """No public callable of the machine module has a name that suggests a command, bypass or valve
    handle. Independent: yes, because the check scans the names.
    """
    # Data names such as the constant RESET_SOURCES are not handles; callables are.
    callables = [
        n
        for n in dir(machine_module)
        if not n.startswith("_") and callable(getattr(machine_module, n))
    ]
    callables += [n for n in dir(prot) if not n.startswith("_") and callable(getattr(prot, n))]
    assert not [n for n in callables if any(f in n.lower() for f in FORBIDDEN)]
    assert "reset" in callables  # the only mutator, guarded by an authorised event


def test_reset_is_the_only_mutator_and_it_demands_an_authorised_event() -> None:
    """The reset is the only public mutator and its argument must be an authorised reset event.
    Independent: yes, because the check inspects the signature.
    """
    parameters = inspect.signature(TankProtection.reset).parameters
    assert parameters["event"].annotation in (AuthorisedReset, "AuthorisedReset")


def test_state_and_latch_are_read_only_properties(prot: TankProtection) -> None:
    """The state and latch are read-only properties. Independent: yes, because the expected outcome
    is the access rule.
    """
    for name in ("state", "trip_latched", "normal_receipt_permitted", "timeout_s"):
        with pytest.raises(AttributeError):
            setattr(prot, name, True)


def test_the_machine_module_imports_no_actuation_or_hydraulic_package() -> None:
    """The machine module imports no actuation or hydraulic package. Independent: yes, because the
    check parses the source.
    """
    tree = ast.parse(Path(machine_module.__file__ or "").read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not [m for m in imported if m.startswith(("verum.graph", "verum.lineups", "verum.api"))]


def test_events_carry_data_only(prot: TankProtection) -> None:
    """The events of the machine are plain data and carry no callable. Independent: yes, because the
    check inspects the event fields.
    """
    trip(prot)
    prot.update(sig(101, ind=13.2))
    for event in prot.events:
        assert not callable(event.requested_valves)
        assert all(isinstance(v, str) for v in event.requested_valves)
