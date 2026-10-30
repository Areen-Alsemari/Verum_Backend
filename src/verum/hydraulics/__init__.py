"""Steady-state network hydraulics: friction, pump, boundaries, solve and gates.

Internal results only; nothing here is exposed through ``verum.api``.
Source: ``revised/02_hydraulic_model.md`` sections 3 and 4.
"""

from verum.hydraulics.boundaries import DeliveryBoundary, ReceiptBoundary
from verum.hydraulics.config import (
    FittingProfile,
    HydraulicConfig,
    load_boundary_law_coefficient,
    load_fitting_profile,
    load_hydraulic_config,
)
from verum.hydraulics.errors import (
    ConvergenceError,
    HydraulicInputError,
    HydraulicsError,
    OverConstrained,
    PropertyScenarioRequired,
    PumpOutsideCurve,
)
from verum.hydraulics.friction import friction_factor, head_loss
from verum.hydraulics.leaks import LeakError, LeakInput
from verum.hydraulics.pump import FixedSpeedPump, PumpElement
from verum.hydraulics.pumping_minimum import pumping_minimum_level
from verum.hydraulics.result import PhaseGate, PumpPoint, SteadyResult
from verum.hydraulics.steady import HydraulicModel, SteadyInputs

__all__ = [
    "ConvergenceError",
    "DeliveryBoundary",
    "FittingProfile",
    "FixedSpeedPump",
    "HydraulicConfig",
    "HydraulicInputError",
    "HydraulicModel",
    "HydraulicsError",
    "LeakError",
    "LeakInput",
    "OverConstrained",
    "PhaseGate",
    "PropertyScenarioRequired",
    "PumpElement",
    "PumpOutsideCurve",
    "PumpPoint",
    "ReceiptBoundary",
    "SteadyInputs",
    "SteadyResult",
    "friction_factor",
    "head_loss",
    "load_boundary_law_coefficient",
    "load_fitting_profile",
    "load_hydraulic_config",
    "pumping_minimum_level",
]
