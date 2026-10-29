"""Exceptions of the steady-state hydraulics package.

Inputs: none. Outputs: exception types. A rejection is an exception; a
physical-validity failure (phase, NPSH) is *not*: it is reported in the result
and the solved values are never clipped.
Key assumption: each exception name states the gate it belongs to.

Source: ``revised/02_hydraulic_model.md`` section 8 (dataset eligibility gates
G2 to G4).
"""

from __future__ import annotations


class HydraulicsError(Exception):
    """Base class for all hydraulics rejections."""


class OverConstrained(HydraulicsError):
    """A pressure and a flow are imposed on the same degree of freedom (gate G2)."""


class PumpOutsideCurve(HydraulicsError):
    """The solved pump flow lies outside the defined curve; it is never extrapolated (G3)."""


class PropertyScenarioRequired(HydraulicsError):
    """No (or an unknown) fluid-property scenario was selected (gate G4)."""


class ConvergenceError(HydraulicsError):
    """The nonlinear solve did not reach the configured tolerance."""


class HydraulicInputError(HydraulicsError):
    """An input is missing or inconsistent (for example a tank level)."""
