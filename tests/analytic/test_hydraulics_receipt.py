"""Receipt splits, signed branch flow, supply cap and boundary rules.

The flow split among open receipt inlets, the source pressure, the supply cap and the
over-constraint rule are compared with documented values and with a reference module that finds the
common source head by a scalar root find. Pressures here are head-based gauge values. The
derivations are in the "Receipt hydraulics" section of the verification notes.

See D3.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import _reference_hydraulics as ref
from _hydraulic_cases import INITIAL_LEVELS, TANKS, receipt_case
from verum.hydraulics import (
    HydraulicModel,
    OverConstrained,
    ReceiptBoundary,
)
from verum.params import ParamValue

CASES = [
    (("TK-101",), [600.0, 0.0, 0.0], 1.050),
    (("TK-102",), [0.0, 600.0, 0.0], 1.154),
    (("TK-103",), [0.0, 0.0, 600.0], 1.258),
    (("TK-101", "TK-102"), [246.41, 353.59, 0.0], 0.783),
    (("TK-101", "TK-103"), [218.88, 0.0, 381.12], 0.772),
    (("TK-102", "TK-103"), [0.0, 265.17, 334.83], 0.696),
    (("TK-101", "TK-102", "TK-103"), [-48.63, 296.10, 352.53], 0.724),
]


@pytest.mark.parametrize(
    ("opened", "split", "pressure_bar"), CASES, ids=["+".join(c[0]) for c in CASES]
)
def test_receipt_splits_match_document_and_reference(
    model: HydraulicModel, opened: tuple[str, ...], split: list[float], pressure_bar: float
) -> None:
    """The flows into the tanks and the source pressure match the documented split and the reference
    root find for each choice of open inlets. Independent: yes, because the reference uses a scalar
    root find and not the Newton solve, though the friction law is the same.
    """
    result = model.solve(receipt_case(opened))
    flows = [result.tank_net_inflow_m3s[t] * 3600 for t in TANKS]
    reference, reference_bar = ref.receipt_flows(INITIAL_LEVELS, list(opened))
    assert flows == pytest.approx(split, abs=0.01)
    assert flows == pytest.approx(reference, abs=1e-6)
    assert result.source_pressure_pa_gauge is not None
    assert result.source_pressure_pa_gauge / 1e5 == pytest.approx(pressure_bar, abs=0.0006)
    assert result.source_pressure_pa_gauge / 1e5 == pytest.approx(reference_bar, abs=1e-7)
    assert sum(flows) == pytest.approx(600.0, abs=1e-6)
    assert result.receipt_flow_m3h == pytest.approx(600.0, abs=1e-6)
    assert not result.receipt_clipped


def test_three_inlet_backflow_is_negative_and_never_clipped(model: HydraulicModel) -> None:
    """With three inlets open the highest tank gives flow back, which is reported as negative and
    never clipped, and its two branches carry equal flow. Independent: yes, because the values come
    from the audited document.
    """
    result = model.solve(receipt_case(TANKS))
    assert result.tank_net_inflow_m3s["TK-101"] * 3600 == pytest.approx(-48.63, abs=0.01)
    assert result.edge_flows_m3s["E-R101a"] < 0 and result.edge_flows_m3s["E-R101b"] < 0
    assert result.edge_flows_m3s["E-R101a"] == pytest.approx(
        result.edge_flows_m3s["E-R101b"], abs=1e-9
    )
    assert result.gates["G6_conservation"] == "OK"


@pytest.mark.parametrize("opened", [c[0] for c in CASES])
def test_receipt_only_cases_have_no_delivery_flow(
    model: HydraulicModel, opened: tuple[str, ...]
) -> None:
    """A receipt-only lineup has no pump and no flow on the delivery edges. Independent: yes,
    because the expected value is zero.
    """
    result = model.solve(receipt_case(opened))
    assert result.pump is None
    assert all(result.edge_flows_m3s[e] == 0.0 for e in ("E-SH", "E-D1", "E-D2", "E-PA2", "E-PB2"))


def test_receipt_total_is_the_configured_600(model: HydraulicModel) -> None:
    """The receipt total is the configured 600 m3/h unless another flow is imposed. Independent:
    yes, because the expected values are the configured and imposed flows.
    """
    assert model.solve(receipt_case(("TK-102",))).receipt_flow_m3h == pytest.approx(600.0, abs=1e-6)
    result = model.solve(receipt_case(("TK-102",), receipt=ReceiptBoundary(flow_m3h=450.0)))
    assert result.receipt_flow_m3h == pytest.approx(450.0, abs=1e-6)


def _with_cap(model: HydraulicModel, cap_pa: float) -> HydraulicModel:
    params = dict(model.config.parameters)
    params["receipt_pressure_cap_pa_gauge"] = ParamValue.selected(cap_pa, "Pa", "SIM", "TEST-CAP")
    return HydraulicModel(
        model.topology, model.geometry, model.fluid, replace(model.config, parameters=params)
    )


def test_the_supply_cap_clips_the_flow_and_is_reported(model: HydraulicModel) -> None:
    """A supply cap below the required pressure is imposed, the flow is reduced and the clipping is
    reported. Independent: yes, because the required pressure is the documented 1.258 barg.
    """
    capped = _with_cap(model, 1.0e5)  # TK-103 needs 1.258 barg for 600 m3/h
    result = capped.solve(receipt_case(("TK-103",)))
    assert result.receipt_clipped
    assert result.source_pressure_pa_gauge == pytest.approx(1.0e5, rel=1e-9)
    assert result.receipt_flow_m3h < 600.0
    assert result.receipt_flow_m3h == pytest.approx(
        ref.flow_at_source_pressure("TK-103", 5.0, 1.0e5), rel=1e-6
    )
    assert any("clipped" in n for n in result.notes)


def test_a_cap_above_the_requirement_does_not_clip(model: HydraulicModel) -> None:
    """A cap above the required pressure leaves the flow at 600 m3/h. Independent: yes, because the
    required pressure is the documented value.
    """
    result = _with_cap(model, 1.3e5).solve(receipt_case(("TK-103",)))
    assert not result.receipt_clipped and result.receipt_flow_m3h == pytest.approx(600.0, abs=1e-6)


def test_the_configured_cap_is_10_barg(model: HydraulicModel) -> None:
    """The configured receipt pressure cap is 10 barg. Independent: yes, because the expected value
    is the stated constant.
    """
    assert model.config["receipt_pressure_cap_pa_gauge"] == 1.0e6


def test_imposed_source_pressure_solves_the_flow(model: HydraulicModel) -> None:
    """Imposing the source pressure solves the flow, which equals the flow that produced that
    pressure in the reference module. Independent: yes, because the pressure comes from the
    reference module.
    """
    pressure = ref.source_pressure_for_single_inlet("TK-102", 7.0, 450 / 3600)
    result = model.solve(
        receipt_case(("TK-102",), receipt=ReceiptBoundary(pressure_pa_gauge=pressure))
    )
    assert result.receipt_flow_m3h == pytest.approx(450.0, rel=1e-6)
    assert result.source_pressure_pa_gauge == pytest.approx(pressure, rel=1e-9)


def test_flow_and_pressure_together_are_over_constrained(model: HydraulicModel) -> None:
    """Imposing both the receipt flow and the source pressure is rejected as over-constrained.
    Independent: yes, because the expected outcome is the boundary rule.
    """
    both = ReceiptBoundary(flow_m3h=600.0, pressure_pa_gauge=2.0e5)
    with pytest.raises(OverConstrained, match="receipt"):
        model.solve(receipt_case(("TK-101",), receipt=both))


def test_receipt_into_a_tank_changes_nothing_on_the_other_tanks(model: HydraulicModel) -> None:
    """Receipt into one tank leaves the other tanks with no net flow. Independent: yes, because the
    expected value is zero.
    """
    result = model.solve(receipt_case(("TK-101",)))
    assert (
        result.tank_net_inflow_m3s["TK-102"] == 0.0 and result.tank_net_inflow_m3s["TK-103"] == 0.0
    )
