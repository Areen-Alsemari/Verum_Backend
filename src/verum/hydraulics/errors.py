"""Exceptions of the steady-state hydraulics package.

A rejection is an exception and each name states the gate it belongs to. A physical-validity failure
(phase, NPSH) is not an exception: it is reported in the result, and the solved values are never
clipped.
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
