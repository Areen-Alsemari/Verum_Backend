"""Configured pumping-minimum tank levels.

For a tank, temperature stratum, fitting profile and NPSH3 coefficient this gives the lowest level
at which the solved delivery operating point passes the phase and NPSH screen. It is separate from
the 1.8 m geometry minimum of the topology and at most equals it. A combination that never passes in
the normal range (1.8 to 12 m) is stored as unresolved, and reading it raises. The levels are for
the duty pump with the delivery boundary law of D2 and the margin ratio of D7.

See D7, D51 and D73.
"""

from __future__ import annotations

import json
from pathlib import Path

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError

FILENAME = "pumping_minimum_levels.json"


WORST_CASE_FACTOR_TAG = {"off": "fd0p8", "v1": "fd0p8", "v2": "fd0p6502"}


def stratum_filename(atmosphere: str, volatility: str, profile: str = "v1") -> str:
    """Name of the table for one atmosphere and volatility pair at the worst-case downstream factor
    of a variability profile.

    The factor is 0.8 for the off and v1 profiles (D51) and 0.6502 for v2 (D73).
    """
    return f"pumping_minimum_levels_{atmosphere}_{volatility}_{WORST_CASE_FACTOR_TAG[profile]}.json"


SITE_PRESSURE_FILENAME = "pumping_minimum_levels_site_pressure.json"


def pumping_minimum_level(
    tank: str,
    temperature_c: float,
    profile: str,
    npsh3_coefficient_m: float,
    directory: Path | None = None,
    filename: str = FILENAME,
) -> ParamValue:
    """The configured pumping-minimum level record for one combination."""
    path = (directory or config_dir()) / filename
    try:
        levels = json.loads(path.read_text(encoding="utf-8"))["levels"]
        raw = levels[tank][f"{temperature_c:g}"][profile][f"{npsh3_coefficient_m:g}"]
        return ParamValue.from_mapping(raw)
    except (OSError, json.JSONDecodeError, KeyError, ParamValueError) as exc:
        raise ContractError(
            f"no pumping-minimum level for {tank}, {temperature_c} C, {profile}: {exc!r}"
        ) from exc
