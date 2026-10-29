# Steady-state network hydraulics

This document describes the steady-state hydraulic model in `verum.hydraulics`.
It covers the equations, the assumptions, the boundary treatment, the sign and
pressure conventions, the limitations and the parameters that are simulation
selections. It describes a model of a synthetic terminal. No part of it has
been validated against a physical installation or against an independent
hydraulic code.

## Scope

The model finds the steady flows and pressures of one lineup, for given tank
levels and boundary conditions. It contains no transients, faults or sensors.
Results are internal: they are not exposed through `verum.api`.

## Unknowns and equations

The unknowns are the total heads H (m) at the nodes of the active network. The
total head is

    H = z + p_gauge / (rho g) + v^2 / (2 g)

with z the node elevation (tank bottom z = 0), p_gauge the static gauge
pressure and v the velocity in the pipe at the node.

**Pipes.** For an edge from node a to node b the head difference is the signed
loss of the flow Q:

    H_a - H_b = ( f(Re) L / D + K ) v |v| / (2 g),     v = Q / (pi D^2 / 4)

D is the inner diameter of the edge itself, so a loss coefficient K acts at the
local velocity. The friction factor f follows decision D14: 64/Re for
Re < 2300, the Haaland expression
`1/sqrt(f) = -1.8 log10[(eps/D/3.7)^1.11 + 6.9/Re]` for Re > 4000, and a linear
blend in Re between 2300 and 4000. The loss increases strictly with |Q|, so each
edge flow is the unique inverse of its head difference. It is found by a
bracketed root find (`scipy.optimize.brentq`).

**Continuity.** At every free node the net outflow equals the external inflow
(zero except at the receipt source in flow mode). The node-balance system is
solved by damped Newton iteration with the Jacobian built from the slope of each
inverse flow law, and a line search on the sum of squared imbalances. The
convergence tolerance on the largest node imbalance is 1e-9 m3/s, a numerical
setting. A solve is accepted only if the node mass imbalance is also below the
conservation tolerance of decision D8 (4.2e-4 kg/s).

**Pump.** The pump node is split into an inlet and an outlet node with the curve
between them:

    H_pump(Q) = H0 s^2 - k (Q / Q_ref)^2,   H0 = 54 m, k = 12 m, Q_ref = 300 m3/h

with s = 1 in this phase. The element is one-way: flow is zero once the head
the pump must add reaches the shutoff head (dead-head). The curve is defined for
0 <= Q/s <= 350 m3/h. A solved flow outside it is rejected with
`PumpOutsideCurve`; it is never extrapolated. Hydraulic power is rho g Q H and
shaft power is hydraulic power divided by the constant efficiency 0.75.

**Check valves** pass flow only in the contract direction. In the pump branch
they act in series with the pump. Receipt branches have no check valves, so
their flow may be negative (flow leaving a tank into the receipt manifold) and
is never clipped.

**Closed valves** remove the edges they touch. Only edges that lie on a flow
path between terminals (the two external boundaries and the tank nozzles) are
solved; a dead-end branch has no flow. Fluid that is open to a tank but not
flowing takes that tank's head, which gives its hydrostatic pressure.

## Boundaries

| Boundary | Treatment |
| --- | --- |
| Tank | Constant-head node at the free-surface level h, atmospheric, bottom at z = 0. The tank inlet and outlet losses sit on the adjoining edge. |
| Receipt | Total flow imposed (600 m3/h), source pressure solved. If the head-based gauge source pressure `rho g (H - z)` would exceed the 10 barg cap, the cap is imposed instead, the flow is solved and the result is flagged as clipped (decision D3). A source pressure may be imposed instead of a flow. |
| Delivery | A reservoir at a gauge pressure of 2 barg lies beyond `DISTRIBUTION_BOUNDARY`. Between the boundary node and the reservoir is the boundary law `dH_d = c (Q/300)^2` (m, Q in m3/h), an element of the solver and not an edge or node of the topology. With c = 0 the boundary node is held at the reservoir head (the pure fixed-pressure boundary). The coefficient c is read per fitting profile from `config/delivery_boundary.json` (decision D2 version 3.0). |

A case that imposes a pressure and a flow on the same degree of freedom is
rejected with `OverConstrained` (gate G2): a receipt flow together with a source
pressure, or a delivery flow together with the fixed reservoir and pump.

## Fitting profiles

Decision D15 defines two profiles of loss coefficients, with a multiplier. In
`pipe_only` all K are zero. In `reference_fittings`: K = 0.3 per polyline bend,
0.5 at a tank outlet, 1.0 at a tank inlet, 0.1 per open isolation valve, 2.0 per
open check valve and 1.0 per meter. A bend is an interior vertex of a route
polyline at which the direction changes, assigned to the edge that contains it
(a bend exactly on a node goes to the downstream edge). A loss belonging to a
node element is charged to the edge that starts there, except the tank inlet,
which is charged to the edge that ends at the tank. Bend positions come from
`config/route_geometry.json`.

## Pressures and sign conventions

- Flow is signed along the contract edge direction (from to). Positive flow runs
  from the first node to the second.
- Static pressure at an edge end or tap:
  `p = rho g (H - z) - rho v^2 / 2`, using the velocity of the edge, or of the
  tap's declared reference edge for a node tap (`config/hydraulics.json`). The
  suction tee uses the DN250 header; `DISTRIBUTION_BOUNDARY` uses `E-D2`.
- All pressures in the result are in Pa gauge. The absolute pressure is
  `gauge + 101325 Pa` (`SteadyResult.to_abs`). Phase screening uses absolute
  pressure.
- The head-based pressure `rho g (H - z)` (static plus dynamic) is used for the
  receipt source pressure and its cap, as in the audited reference figures.
  The `PT-203` expression of decision D2, 2 barg + `rho g dH_d`, is this
  head-based pressure at the boundary node; the reported static pressure is
  lower by `rho v^2 / 2` (about 2.5 kPa at 300 m3/h).

## Phase and NPSH gate

The vapor pressure `p_v(T)` comes from a named property scenario
(`EPA_GENERIC_RVP10_REFERENCE`, the generic reference correlation of the fluid
contract) at 25, 35 or 45 C (decision D11). A missing or unknown scenario is
rejected with `PropertyScenarioRequired`. Hydraulic properties (density,
viscosity) stay at their 25 C constants.

    NPSHa = (p_atm - p_v) / (rho g) + (H_in - z_pump)
    NPSH3 = a (Q / 300)^2   (a = 4 m, decision D7), evaluated at the solved flow

where `H_in` is the total head at the pump inlet. The gate status is:

- `SCREEN_FAILED` if any active edge end has an absolute pressure below `p_v`,
  or `NPSHa <= 0`;
- `NPSH_MARGIN_FAILED` if `NPSHa / NPSH3 < 1.3`;
- `OK` otherwise.

A failure is reported in the result. The solved flows and pressures are left as
solved; nothing is clipped. The derived pumping-minimum tank levels are stored
in `config/pumping_minimum_levels.json` and are separate from the 1.8 m geometry
minimum.

## Parameters that are simulation selections

All values in the hydraulic configuration are provisional design or simulation
selections with a provenance identifier:

- the pump curve (54 m, 12 m, 300 and 350 m3/h) and efficiency 0.75;
- the receipt flow 600 m3/h and the 10 barg cap (decision D3);
- the reservoir pressure 2 barg and the boundary-law coefficients (D2);
- the fitting profiles (D15, typical handbook values, unverified);
- the NPSH3 relation and margin 1.3 (D7), and the temperature strata (D11);
- the roughness 4.5e-5 m, the atmosphere 101325 Pa and the pipe bores (design
  values of the package);
- the solver settings (tolerance 1e-9 m3/s, 100 iterations), chosen for this
  phase and not taken from the audited documents.

The vapor-pressure correlation is a generic published reference, not a PG95
assay.

## Limitations

- Steady state only. There is no wave propagation, valve or pump motion, or
  check-valve closure.
- The pump curve is synthetic. No independent validation against a
  manufacturer curve or a measured system exists, and none is possible for this
  configuration.
- The friction blend is a numerical device, and the fitting values are
  unverified handbook figures.
- Tank nozzles are held at the free-surface head; there is no jet or vortex
  model and no tank outlet geometry effect beyond the loss coefficient.
- Partial valve opening is not modelled: open valves have the full-open K.
- The model does not check that a lineup is an allowed mode; it accepts any
  combination of open valves and running pumps (the three-inlet receipt case of
  the audit is reproduced this way as a counterexample).
- Tests of this model compare it with closed-form series solves and with figures
  from the audited reference package. They are tests of a reduced model, not
  independent validation of the hydraulics.
