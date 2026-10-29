"""Transient (method of characteristics) engine for the 28-edge network, as a library.

Inputs: a steady solve of ``verum.hydraulics`` and the events of a transient (valve strokes,
set-point changes, a pump stop). Outputs: heads and flows at every grid point as a function of
time, diagnostics and a mass ledger.
Key assumptions:
    * Standalone: it does not touch ``verum.sim``, the truth store or the gateway, and it is not
      called by them (decision D47). It imports only hydraulics configuration, friction and
      valve laws.
    * First-order method of characteristics, one common time step, per-edge wave-speed
      adjustment, ideal mass-conserving junctions (decision D43).
    * No cavitation model: nodes at or below the vapor pressure are flagged and nothing from
      such an interval is usable (decision D45).
    * Self-built: verified against closed forms and other codes, which is verification and not
      validation.

Source: ``docs/design_decisions.md`` D43 to D47; ``docs/transient_engine.md``.
"""

from verum.transient.driver import TransientEngine, TransientSpec

__all__ = ["TransientEngine", "TransientSpec"]
