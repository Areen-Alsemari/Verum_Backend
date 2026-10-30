"""Transient (method of characteristics) engine for the 28-edge network, as a library.

From a steady solve and a list of events (valve strokes, set-point changes, a pump stop) it gives
heads and flows at every grid point over time, with diagnostics and a mass ledger. It is standalone
and is not called by the simulation, the truth store or the gateway. It is first order, with one
common time step and ideal junctions. There is no cavitation model, so nodes at or below the vapor
pressure are flagged and nothing from such an interval is usable. It is verified against closed
forms and other codes, which is verification and not validation.

See D43 to D47.
"""

from verum.transient.driver import TransientEngine, TransientSpec

__all__ = ["TransientEngine", "TransientSpec"]
