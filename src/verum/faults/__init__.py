"""Single-fault injection (hidden side).

Specification records and their validation, the injector that acts through physical parameters and
the sensor-chain hook, and the hidden ``fault_truth`` rows. Nothing here is reachable from
``verum.api``; ``verum.sensors`` knows only the hook call signature, not this package.
Source: ``docs/fault_models.md``.
"""

from verum.faults.activity import LineupState, activity, lineup_states, on_parallel_branch
from verum.faults.injector import FaultSet, SensorFaultHook, ValveFault
from verum.faults.spec import FaultSpec, from_record
from verum.faults.truth import fault_truth_rows, instance_ids
from verum.faults.validate import check, violations

__all__ = [
    "FaultSet",
    "FaultSpec",
    "LineupState",
    "SensorFaultHook",
    "ValveFault",
    "activity",
    "check",
    "fault_truth_rows",
    "from_record",
    "instance_ids",
    "lineup_states",
    "on_parallel_branch",
    "violations",
]
