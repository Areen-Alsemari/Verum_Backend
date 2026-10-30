"""Configuration of the independent protection logic for one tank.

The level thresholds come from the topology contract, and the isolation-timeout multiplier,
residual-flow threshold, valve stroke times and contact lags from the protection configuration, all
as parameter records. The isolation timeout is the multiplier times the stroke time plus the contact
lag, for each requested valve, and the request's timeout is the largest of them. The request closes
the common receipt valve and the inlet valve of the tripped tank, which is a proposal because the
audited text names no valves. Alarm and reset hysteresis lower the levels at which the high alarm
clears and a latched trip can be reset.

See D4, D12, D13 and D16.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.contracts.topology import Tank, Topology
from verum.params import ParamValue, ParamValueError

FILENAME: Final = "protection.json"
COMMON_RECEIPT_VALVE: Final = "XV-R000"


@dataclass(frozen=True)
class ProtectionConfig:
    """Thresholds and timing for the protection of one tank."""

    tank_id: str
    high_alarm_m: float
    high_high_m: float
    timeout_multiplier: ParamValue
    residual_flow_m3h: ParamValue
    hysteresis: ParamValue
    stroke_time_s: dict[str, ParamValue]
    contact_lag_s: dict[str, ParamValue]

    @property
    def isolation_valves(self) -> tuple[str, ...]:
        """Valves whose closure is requested on a high-high trip."""
        return (COMMON_RECEIPT_VALVE, f"XV-R{self.tank_id[3:]}")

    def valve_timeout_s(self, valve: str) -> float:
        """Confirmation timeout for one valve: multiplier x stroke + lag."""
        try:
            stroke, lag = self.stroke_time_s[valve], self.contact_lag_s[valve]
        except KeyError:
            raise ContractError(f"protection config: no stroke time or lag for {valve}") from None
        return self.timeout_multiplier.value * stroke.value + lag.value

    def timeout_s(self) -> float:
        """Confirmation timeout of a request: the slowest requested valve."""
        return max(self.valve_timeout_s(v) for v in self.isolation_valves)

    @property
    def alarm_clear_m(self) -> float:
        """Level below which HIGH_ALARM clears: alarm level minus the hysteresis."""
        return self.high_alarm_m - self.hysteresis.value

    @property
    def reset_ceiling_m(self) -> float:
        """Level below which a high-high latch may be reset: trip level minus the hysteresis."""
        return self.high_high_m - self.hysteresis.value

    @property
    def residual_flow_threshold_m3h(self) -> float:
        return self.residual_flow_m3h.value


def _records(raw: dict[str, dict[str, object]]) -> dict[str, ParamValue]:
    return {k: ParamValue.from_mapping(v) for k, v in raw.items()}


def parse_protection_config(raw: dict[str, object], tank: Tank) -> ProtectionConfig:
    """Build the configuration for one tank from a decoded file."""
    try:
        p = raw["parameters"]
        assert isinstance(p, dict)
        dims = tank.dimensions_m
        return ProtectionConfig(
            tank_id=tank.tank_id,
            high_alarm_m=dims["high_alarm_m"],
            high_high_m=dims["independent_high_high_m"],
            timeout_multiplier=ParamValue.from_mapping(p["isolation_timeout_stroke_multiplier"]),
            residual_flow_m3h=ParamValue.from_mapping(p["residual_flow_threshold_m3h"]),
            hysteresis=ParamValue.from_mapping(p["alarm_hysteresis_m"]),
            stroke_time_s=_records(p["stroke_time_s"]),
            contact_lag_s=_records(p["contact_lag_s"]),
        )
    except (KeyError, AssertionError, ParamValueError) as exc:
        raise ContractError(f"protection config: {exc!r}") from exc


def load_protection_config(
    topology: Topology, tank_id: str, directory: Path | None = None
) -> ProtectionConfig:
    """Load the protection configuration for a tank of the topology."""
    tank = next((t for t in topology.tanks if t.tank_id == tank_id), None)
    if tank is None:
        raise ContractError(f"protection config: unknown tank {tank_id!r}")
    path = (directory or config_dir()) / FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return parse_protection_config(raw, tank)
