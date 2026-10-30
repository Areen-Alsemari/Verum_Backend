"""Single-fault injection, on the hidden side.

The package holds the fault specifications and their validation, the injector that acts through
physical parameters and a sensor-chain hook, and the hidden fault-truth rows. Nothing here is
reachable from the gateway, and the sensor package knows only the signature of the hook.

See docs on fault models.
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
