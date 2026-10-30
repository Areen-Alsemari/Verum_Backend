"""True vapor pressure for a named property scenario.

A scenario must be named: none, or an unknown name, raises and there is no default. The scenarios
are the volatility classes and the legacy name of the RVP 10 reference, and none is an assay of the
product. Hydraulic properties stay at their 25 C constants, so the temperature enters only the phase
and NPSH screens. The result is in Pa absolute.

See D11 and D46.
"""

from __future__ import annotations

import math
from typing import Final

from verum.contracts.fluid import FluidContract
from verum.hydraulics.config import HydraulicConfig
from verum.hydraulics.errors import PropertyScenarioRequired

PSI_TO_PA: Final = 6894.757293
KELVIN_OFFSET: Final = 273.15


def vapor_pressure_pa(
    scenario: str | None, temperature_c: float, config: HydraulicConfig, fluid: FluidContract
) -> float:
    """True vapor pressure (Pa abs) of the named scenario at a temperature."""
    if scenario is None:
        raise PropertyScenarioRequired("no property scenario selected")
    if scenario not in config.scenarios:
        raise PropertyScenarioRequired(f"unknown property scenario {scenario!r}")
    if (
        scenario in config.derived_vapor_constants
    ):  # derived class (decision D46); may be unresolved
        a_rec, b_rec = config.derived_vapor_constants[scenario]
        a, b = a_rec.value, b_rec.value
    else:
        if config.scenarios[scenario] != fluid.vapor_reference_id:
            raise PropertyScenarioRequired(
                f"scenario {scenario!r} does not match the fluid contract's vapor reference"
            )
        a = fluid.vapor_constants["A"].value
        b = fluid.vapor_constants["B_degR"].value
    temperature_k = temperature_c + KELVIN_OFFSET
    return PSI_TO_PA * math.exp(a - b / (1.8 * temperature_k))
