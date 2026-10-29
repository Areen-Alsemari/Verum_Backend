"""Configured pumping-minimum tank levels.

Inputs: ``config/pumping_minimum_levels.json``, produced by the Phase 2 study.
Outputs: the lowest tank level at which the solved delivery operating point
passes the phase and NPSH screen, for a tank, temperature stratum, fitting
profile and NPSH3 coefficient, as a ``ParamValue``.
Key assumptions:
    * This level is separate from, and does not replace, the 1.8 m geometry
      minimum of the topology contract. At most it equals 1.8 m, when the
      geometry minimum already passes.
    * A combination that never passes inside the normal range (1.8 to 12 m) is
      stored as an unresolved record; reading its value raises
      ``UnresolvedParameter``.
    * The levels are computed for the duty pump A with the delivery boundary law
      of decision D2 version 3.0 and the margin ratio of decision D7.
    * ``SITE_PRESSURE_FILENAME`` names a sensitivity table for a lower
      atmospheric pressure (94300 Pa); it never replaces the sea-level table.

Source: ``docs/design_decisions.md`` D7 (version 2.0); the study script
``local/tools/phase2_studies.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from verum.contracts.errors import ContractError
from verum.contracts.paths import config_dir
from verum.params import ParamValue, ParamValueError

FILENAME = "pumping_minimum_levels.json"
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
