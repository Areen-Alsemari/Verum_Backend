"""True vapor pressure for a named property scenario.

Inputs: a scenario name, a temperature, the fluid contract's vapor-reference
constants and the configured scenario table. Outputs: vapor pressure in Pa
absolute.
Key assumptions:
    * A scenario must be named. ``None`` or an unknown name raises
      ``PropertyScenarioRequired``; there is no default scenario.
    * The scenarios are the volatility classes of decision D46 (RVP10 from the fluid contract,
      RVP_9_0 and RVP_9_5 from the AP-42 correlation behind a verification gate) and the legacy
      name of the RVP 10 reference; none is a PG95 assay.
      Hydraulic properties stay at the 25 C constants (decision D11); the
      temperature enters the phase and NPSH screens only.
    * ``6894.757293`` converts psi to Pa and ``273.15`` converts degC to K; both
      are unit conversions.

Source: ``fluid_contract.json`` (vapor_reference);
``docs/design_decisions.md`` D11; ``revised/02_hydraulic_model.md`` section 1.1.
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
