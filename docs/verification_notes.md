# Verification notes

Hand derivations and sampling-error arguments behind the tests, with one section per test module. A test docstring points to its section by name.

## Demand process

Key assumptions:

- Specified values (decision D23): standard deviation of log f_d 0.05, correlation time 1800 s, clip to [0.8, 1.25], stream `demand`, grid of one second.
- Sampling error. For a stationary OU series of length T the sample mean has standard deviation sigma sqrt(2 tau / T), and the sample variance has relative standard deviation sqrt(2 tau / T); with T = 8e6 s and tau = 1800 s these are 1.06e-3 and 0.0212. Tolerances are four standard deviations. The autocorrelation at lag k must be exp(-k/tau); its sampling variance for an AR(1) series is (Bartlett) [(1 + phi^2)(1 - phi^(2k))/(1 - phi^2) - 2 k phi^(2k)] / N, phi = exp(-1/tau), which is 0.0142 squared at k = 900 s and N = 8e6.

Independence: the targets are the specified values and the sampling-error formulas above (hand derivation), not outputs of the code under test.

### S0f delivery flow responds to the factor with the hand slope

The flow depends on f_d and on the falling tank level; separate them by least squares.

Hand derivation: at the duty point the head balance is pump(Q) = static + loss(Q) + c f_d (Q/300)^2, so dQ/df = -c (Q/300)^2 / S with S the slope of loss + law - pump with respect to Q (central difference of the reference module, TK-102 reference fittings). The level coefficient is +1/S per metre. A plain correlation with f_d alone is only about -0.8 because the level falls 0.44 m in the hour, a trend of the same size as the factor's effect (2 m3/h); the regression on both removes it.

Independent: the slope uses the separate reference implementation of the friction law.

## Engine accuracy

Derivations (hand arithmetic):

- S0-B. The receipt flow starts at 0 and follows q(t) = Q (1 - exp(-t/tau)), Q = 600 m3/h, tau = 2 s. The volume received in time T is Q T - Q tau (1 - exp(-T/tau)), so after 3600 s it is 600 m3 - 0.33333 m3 (the transient deficit Q tau = 600/3600 x 2). With A = 706.858 m2 on the floating branch, the level rise is (600 - 0.33333)/706.858 = 0.848826 - 0.000472 = 0.848354 m. The Phase 3 engine added the trapezoid error of the Heun stage average, (dt^2/12) q'(0) / A = 1.0e-5 m at dt = 1 s; the implicit integration of Phase 3b removes it.
- Accuracy target (decision D17): level error <= 0.025 mm = 2.5e-5 m.
- REJ-2. From 6.46 m to the stored minimum 6.278 m (coastal, RVP_9_0, f_d = 0.8) the level falls 0.182 m, i.e. 128.6 m3; at about 301 m3/h (0.0836 m3/s) that takes about 1539 s.

Independence: the S0-B reference is a closed-form expression (independent). The S0-A, S0-C and REJ-2 references integrate the same steady flow function (the production hydraulic model) with an adaptive RK45 scheme, so they are independent in the time integration only, not in the hydraulics. The step-halving study uses the S0-B closed form for the order, and the RK45 reference for S0-A.

### S0b error is independent of the step and far below the target

The receipt flow ODE is integrated implicitly to a tolerance, not on the step grid.

Independent (closed form of S0-B). The Phase 3 engine had the Heun trapezoid error (dt^2/12) q'(0) / A = 1.0e-5 m at dt = 1 s and second-order convergence; the present integrator carries no step-size error, so the error sits at the integrator tolerance for every grid step and the 2.5e-5 m target is met with a margin of more than four orders.

## Valve restriction, pump degradation and misrouting

Derivations (hand arithmetic):

- Valve loss (D19, D4): K(alpha) = 0.1 (1/Kv_fraction)^2 with Kv_fraction = 50^(alpha - 1) above alpha_c = 0.05 and 0.4 x 50^-0.95 = 0.009728 at alpha = 0.02. Hence K(0.5) = 0.1 x 50 = 5.0, K(0.9) = 0.1 x 50^0.2 = 0.2187, K(0.15) = 0.1 x 50^1.7 = 77.3 and K(0.02) = 1056.7.
- Pump: H(Q) = h (54 - 12 (Q/300)^2) for a head scale h. The delivery of TK-102 at 7 m with the reference fittings has the series path of `_reference_hydraulics` (segments counted by hand there) and the boundary law with c = 10.0609 m; the operating flow is the root of pump head - required head, found by `brentq` in the reference module's functions.
- Misrouting (a): XV-R101 and XV-R102 open with 600 m3/h received and TK-101 at 9 m, TK-102 at 7 m: the split is the root of the two branch equations in the reference module.
- Misrouting (b): the pump branch valve XV-PAO at alpha 0.02 adds K(0.02) = 1056.7 at the DN200 pump branch; the reference path gets a segment with that coefficient and no length.
- The valve contact (D31) asserts at 0.98 and releases below 0.97: a ceiling of 0.5 reached linearly over 30 s from 300 s releases the contact at 300 + 30 x (1 - 0.97) / 0.5 = 301.8 s.

Independence: the reference module solves the series path by a scalar root find and does not import the package; the valve law values are hand arithmetic.

- Restriction modes (D74): in both modes the loss is K(0.5) = 5.0 (the valve adds 4.9 to the open-valve loss); a visible restriction releases the open contact at 301.8 s, an obstruction leaves it asserted.

## Pipe leak

Derivations (hand arithmetic):

- Orifice: Q = Cd A sqrt(2 p / rho). With Cd 0.62, A 1e-3 m2, p 200 kPa, rho 750 kg/m3: sqrt(2 x 200000 / 750) = 23.094 m/s, Q = 0.62 x 1e-3 x 23.094 = 0.014318 m3/s.
- The steady-network cases read the solved gauge pressure at the leak (the quantity of D60, rho g (H - z)) and evaluate the formula on it, so the expected flow is independent of the orifice implementation but uses the pressure of the solve.
- Doubling the area at fixed pressure doubles the flow (the law is linear in A).
- Mass: in the steady solve the tank gives up the pump flow plus a suction-side leak; the engine ledger is received - delivered - spilled - change of tank inventory.
- Rigid column against the transient engine: the transient engine holds the tank level constant and puts the sink at the junction RECEIPT_HEADER (the end of E003), the rigid-column leak is at 0.95 of E003, 5.25 m upstream. The pressure at the two points differs by the friction of 5.25 m of DN300 at about 2.3 m/s (f 0.0155: 0.0155 x 5.25 / 0.30318 x 2.31^2 / 19.61 = 0.073 m, 0.56 % of a head of 13 m), which changes the leak flow by half of that, 0.3 %. The inertial head the rigid column misreads during the ramp is at most Lambda dQ_L/dt = 311 s2/m2 x (0.006 m3/s / 300 s) = 0.006 m, 0.05 %. The tolerance is therefore 1 percent of the final leak flow plus the noise of the 10 s mean (0.5 %).

Independence: the formula and the tolerance are hand values; the transient engine is a separate model of the same equations, not independent validation of the facility.

## Headroom screen and level envelope

Derivation of the expected values (independent of the package code), with A = 225 pi = 706.858347058 m2, V_post = 20 m3, dh = 0.05 m, HH = 13 m, CH = 14 m (available headroom 1 m): rise(Q, t) = (Q t + V_post) / A + dh 600 m3/h, 1 h : (600 + 20) / A + 0.05 = 0.877121 + 0.05 = 0.927121 m margin 1 - 0.927121 = 0.072879 m 660 m3/h, 1 h : (660 + 20) / A + 0.05 = 1.012003 m -> required height 14.012003 m, fails 900 m3/h, 1 h : (900 + 20) / A + 0.05 = 1.351 m, fails 600 m3/h, 2 h : (1200 + 20) / A + 0.05 = 1.776 m, fails limiting flow for 1 h: Q = (0.95 A - 20) m3/h = 651.515 m3/h normal/high screen, 15 min at 600 m3/h: (150 + 20) / A + 0.05 = 0.290501 m receipt level rise: 600 m3 / A = 0.848826 m

Same-formula note: the rise expression is the definition of screen E7 and is the same expression as in the implementation; the independent parts are the decimal arithmetic, the literal values from the audited document, and the pass/fail outcomes.

## Delivery hydraulics

Derivations (independent of the package, except where stated):

- Closed-form series solve: the delivery path is one series line (tank, suction branch, DN250 header, pump branch, distribution main). The pump head equals the static difference plus the boundary law plus the summed Darcy losses; the operating flow is the root of that scalar equation (brentq). This is a different method from the node-head Newton solve.
- Required pump head at 300 m3/h, pipe-only, fixed 2 barg boundary: H = 200000/(rho g) + (0.5 - h) + losses(300 m3/h); with 27.19 m of boundary head, 8.589 m of losses and h = 9 m this is 27.281 m (audited document); the speed ratio follows from 54 s^2 - 12 = H.
- Reference-fittings TK-102 path: total K counted by hand (see `_reference_hydraulics.tank2_reference_fittings_segments`).
- Document values quoted below come from the audited reference package. The D2 operating points (312.6, 300.0, 287.5 m3/h) come from the audited reference script with the D2 resistance added (decision record D2).

Independence of the friction law: same law as the package (see `test_hydraulics_friction.py`).

## Friction law

Derivation of the expected values (hand arithmetic, DN200, 300 m3/h): Q = 300/3600 = 0.083333 m3/s; A = pi 0.20274^2 / 4 = 0.032283 m2; v = 2.5813 m/s; Re = 750 x 2.5813 x 0.20274 / 0.0005 = 7.85e5 (turbulent). eps/D = 4.5e-5/0.20274 = 2.2196e-4; (2.2196e-4/3.7)^1.11 = 2.055e-5; 6.9/Re = 8.79e-6; sum 2.934e-5; log10 = -4.5326; 1/sqrt(f) = 8.1587; f = 0.015023. Head loss over 250 m: 0.015023 x (250/0.20274) x (v^2/2g = 0.33964 m) = 6.292 m by hand, which the audited document gives as 6.296 m.

Independence: the document figures (6.296, 0.279, 0.504, 1.875 m) were produced by the audit's script, and the hand arithmetic above is separate from the package. The friction law itself (D14) is the same law in the package, the document and `_reference_hydraulics`; the tests therefore do not check the law's physical validity, only its correct implementation.

## Static pressures and NPSH

Derivations:

- Static pressure at a tap: p = rho g (H - z) - rho v^2 / 2, with the velocity of the tap's reference edge. At the pump suction tee the reference edge is the DN250 header, A = pi 0.25446^2 / 4 = 0.050853 m2; at 300 m3/h v = 1.6388 m/s and v^2/(2g) = 0.13691 m (document: 0.136908).
- PT-201 at 300 m3/h and 1.8 m, pipe-only: head at the tee is 1.8 - losses(tank branch, header); the document values are -0.046 / -0.102 / -0.157 barg for TK-101 / 102 / 103.
- Across the pump (same bore, same elevation, same velocity) the static pressure rises by exactly rho g times the head rise.
- NPSHa at TK-102, 7 m, 25 C, 300 m3/h: (101325 - 49199)/(rho g) + (7 - 0.5)
- losses = 10.79 m (document section 4). The solved flow of that case is 300.0 m3/h, so the document's fixed 300 m3/h applies.
- Vapor pressures of the reference correlation: 35.065 / 49.199 / 67.530 / 90.863 kPa at 15 / 25 / 35 / 45 C (document section 1.1).

Independence: the document values are from the audit; the identities are hand arithmetic. The tap formula is the one the package implements (stated in the task), so the check on it is the identities and the document numbers.

## Receipt hydraulics

Derivations:

- Single inlet i: the source head (above its 1.0 m datum) is h_i - 1 + loss(600 m3/h, DN300, 150 m) + loss(600 m3/h, DN200, branch length); the source pressure is rho g times that head. Document values: 1.050 / 1.154 / 1.258 barg at 9 / 7 / 5 m.
- Several open inlets: one common source head satisfies every branch law; the branch flows sum to 600 m3/h. The reference finds it by brentq. A branch whose tank is above the common head carries negative flow (flow leaves the tank); the document gives -48.63 / 296.10 / 352.53 m3/h at 0.724 barg for three open inlets.
- Pressures here are head-based gauge values (rho g (H - z)), as in the audited document, not static pressures.

Independence: the document values come from the audit's script; the reference code is a different method (scalar root finds) from the Newton solve. The friction law is the same law (decision D14).

## Partly closed valve

Derivation (hand arithmetic, independent of the code): with XV-R101 half open the loss coefficient of the valve is K(0.5) = 0.1 x 50 = 5.0 instead of the profile's 0.1. The valve sits on the DN200 edge E-R101b, so at 600 m3/h (v = 0.16667 / 0.032283 = 5.163 m/s) the head at the source rises by (5.0 - 0.1) v^2 / (2 g) = 4.9 x 1.3589 = 6.659 m and the head-based source pressure by rho g x 6.659 = 48.98 kPa. Friction is unchanged. A closed valve (alpha at or below the threshold) removes the path; the cap clips the flow when the source pressure would exceed 10 barg.

## Inventory ledger

Derivation of the expected values (independent of the ledger code), with rho = 750 kg/m3, A = 706.858347 m2: 600 m3/h for 1 h  : 600 m3 = 450000 kg; level rise 600 / A = 0.848826 m 600 in, 300 out   : net 300 m3 = 225000 kg; level rise 300 / A = 0.424413 m leak of 5 m3      : 3750 kg leave the network once; the tank gains 450000 - 3750 = 446250 kg round-off bound   : (n - 1) 2^-53 sum|x|, e.g. terms [1, 2, -3] give 2 * 2^-53 * 6 = 12 * 2^-53

Same-formula note: the closure residual is computed from the same cumulative sums the ledger keeps, so for exactly representable flows it equals zero by construction. The tests that carry information are the externally derived inventory and level changes, the detection of an injected double subtraction or an unbalanced step, and the property test over arbitrary flows that checks the residual against the stated bound.

## Rigid-column path dynamics

Derivations (hand arithmetic):

- Inertance. The receipt path to TK-101 is 150 m of DN300 (A = 0.0721936 m2) and 45 m of DN200 (A = 0.0322811 m2): sum L/A = 2077.7 + 1394.0 = 3471.7 1/m, I = sum L/(g A) = 354.0 s2/m2.
- Surge. Along the flow the head drops by the loss plus (L/(g A)) dQ/dt, so at the source the head exceeds the quasi-steady head by I dQ/dt. In S0-B Q(t) = (600/3600)(1 - exp(-t/2)), so dQ/dt(1 s) = (600/3600)/2 exp(-1/2) = 0.050544 m3/s2 and the surge is 17.9 m.
- Cap. The supply cap of 10 barg is a head of 1 m + 1e6/(750 x 9.80665) = 136.96 m at the source. Under the cap dQ/dt = (H_cap - H_source(Q))/I, so the source head is the cap and the offset to the quasi-steady head is I |dQ/dt|.
- Delivery step response. For a small departure from the duty point the column relaxes with rate k = (d/dQ)[loss + c (Q/300)^2 - pump head] / I.
- Lag. A column that follows a slowly moving equilibrium lags it by tau dQ_eq/dt, with tau = 1/k; the volume it delivers over the hour then differs from the quasi-steady volume by tau (Q_eq(end) - Q_eq(0)).

Independence: the closed forms, the hand inertance and the cap head are independent of the code under test. The reference losses come from `_reference_hydraulics` (a separate implementation of the same friction law, so the law itself is not independently tested). The quasi-steady reference heads come from the steady solver (the same formulas as the engine's lumped path; this is stated in each such test).

### The s0a volume differs from the quasi steady one by the hand lag

The delivery column lags the slowly falling duty flow by tau dQ_eq/dt (hand derivation).

Integrated over the hour the lag is tau (Q_eq(end) - Q_eq(0)) with tau = 1/k. With the TK-101 path inertance 1112.6 s2/m2 and the loss-plus-pump slope at the duty point, k = 0.7257 1/s, tau = 1.378 s, and the flow falls by 0.00049 m3/s over the hour, so the quasi-steady volume exceeds the engine's by about 6.7e-4 m3 (1.0e-6 m of level). The engine's pump flow rows give Q_eq(0) and Q_eq(end).

### Pt001 surge head is the downstream inertance times the flow rate

S0-B ramp, with the tap anchored by decision D36: head(PT-001) - (quasi-steady source head - loss_up) = (I - Lambda_up) dQ/dt, the inertance of the column from the tap to the tank (290.5 s2/m2 by hand: 354.0 - 63.56), with dQ/dt from the closed form.

The quasi-steady source head is a steady solve at the logged flow and level (same formulas as the engine's lumped path, so this checks the offsets, not the loss law); loss_up is the hand loss of E001 and E002 from the separate reference implementation.

### The esd decay time lies between the hand bounds

Hand bounds on the decay of the flow (90 % to 10 %) in the 10 s closure under the cap.

The cap binds when the valve loss at 600 m3/h reaches the head budget, alpha* = 0.03165 (hand: K = 421.8 from the budget 136.96 - 13 - 9.37 m over v^2/2g = 0.27175 m, Kv ratio sqrt(0.1/421.8) = 0.015398, linear branch alpha = ratio x 0.05 / 50^-0.95). Until then the flow is 600 m3/h; afterwards it cannot fall below the cap-limited flow 600 alpha/alpha* (the column lags the equilibrium from above). The 90 % flow therefore occurs no earlier than alpha = 0.9 alpha* = 0.02849, 9.715 s into the stroke, and the valve is closed at 9.99 s, so the decay time is at most 0.275 s. The collapse is faster than 10 wave round trips of the path (3.6 s), which is why it is a validity window.

## PT-001 anchor

Derivations (hand arithmetic):

- Lambda_up. E001 (30 m) and E002 (15 m) are DN300, bore 0.30318 m, area 0.0721923 m2, so Lambda_up = 45 / (9.80665 x 0.0721923) = 63.56 s2/m2 (the whole column is 354.0).
- Losses upstream. E001 has no local loss and E002 the receipt meter, K = 1.0 (hand count, reference fittings). loss_up(Q) = f L/D v^2/2g over 45 m + 1.0 v^2/2g.
- Open flow state (dQ/dt = 0): head at PT-001 = H_source - loss_up, with H_source the head at the start of E001, read back from the written pressure at the start of E001 (z + p/(rho g) + v^2/2g).
- Capped, decelerating: H_source is the cap head 1 m + 1e6/(750 x 9.80665) = 136.96 m, so the head at PT-001 is the cap minus loss_up plus Lambda_up |dQ/dt|.
- Identity: the head at PT-001 equals the head at the end of E002 at every row, because both are the source head less the same loss and inertial terms of E001 and E002.

Independence: Lambda_up, loss_up and the cap head are hand values (the loss comes from the separate reference implementation of the friction law). The identity compares two written quantities and is not a test of the loss law.

## PT-001 at the start of E002

Derivations (hand arithmetic):

- Lambda_up for E001 only: 30 m of DN300 (bore 0.30318 m, area 0.0721923 m2): 30 / (9.80665 x 0.0721923) = 42.37 s2/m2. With E002 (15 m) it is 63.56 s2/m2.
- Observed PT-001 (start of E002): H_source - loss(E001) - Lambda_E001 dQ/dt. E001 has no local loss, so loss(E001) is the friction of 30 m of DN300.
- Open flow state: dQ/dt = 0. Capped and decelerating: H_source is the cap head 136.96 m and the head is the cap - loss(E001) + Lambda_E001 |dQ/dt|.
- Hidden node value at the end of E002: H_source - loss(E001, E002) - Lambda_(E001+E002) dQ/dt, labelled `end_of_E002_lambda_E001_E002` in the node row.
- Identity: with the same dQ/dt along the column, (H_from - H_to - loss)/Lambda is the same number for E001 and E002 at every row.

Independence: Lambda and the losses are hand values (the losses from the separate reference implementation of the friction law); the identity compares written quantities.

## Receipt inertial dip

Derivations (hand arithmetic; bore 0.30318 m has area 0.0721923 m2 and bore 0.20274 m has area 0.0322828 m2):

- Lambda = sum L/(g A) over the edges downstream of the start of E002 (the PT-001 tap): E002 + E003 = 120 m of DN300: 120 / (9.80665 x 0.0721923) = 169.50 s2/m2; E-R101a + E-R101b = 45 m of DN200: 45 / (9.80665 x 0.0322828) = 142.14 s2/m2; sum 311.64 s2/m2. Beyond the end of E002 (the hidden tap node): 105 m of DN300 + 45 m of DN200 = 290.45 s2/m2.
- The receipt controller is first order with time constant tau = 2 s (configuration): dQ/dt = (Q_set - Q) / tau. A step from 600 to 300 m3/h gives dQ/dt = -150 m3/h/s = -0.0416667 m3/s2 at the command; the head at the start of E002 falls at once by Lambda dQ/dt = 311.64 x 0.0416667 = 12.985 m, which is 12.985 x 750 x 9.80665 = 95.5 kPa.
- The head at the start of E002 is H = Z + h_tank + sum loss(Q) + Lambda dQ/dt over the downstream edges (the receipt column is anchored at the tank). Z is a constant that is fixed from the row before the step, where dQ/dt = 0, so only the dependence on Q and dQ/dt is tested.
- For each of E001 and E002, (H_from - H_to - loss(Q)) / Lambda_edge equals dQ/dt (the same identity as in `test_pt001_start_of_e002`).

Independence: Lambda and the losses are hand values (the losses from the separate reference implementation of the friction law, with the fitting coefficients of the configuration); the rate of change comes from the first-order law and the written flows. The transient-engine comparison is a separate calculation (elastic waves, method of characteristics); its pressure oscillates about the rigid-column value, mainly at 1.0 s (and 0.41 s), which are periods of the whole network (the closed branches at the header), not of the receipt path alone: a first window of 4 L / a of the path (0.72 s) was a wrong premise, because it does not remove them. The comparison therefore uses the mean over a window of 2.0 s (twice the longest period, so it also removes the second harmonic), centred on the instant, and the tolerance is 10 percent of the dip magnitude Lambda |dQ/dt| at that instant. This is a comparison of two models of the same equations in their common range, not validation against measurement.

## Sensor chain

Derivations (hand arithmetic):

- Lag step response. A unit step at t0 into a first-order lag of constant tau gives y = 1 - exp(-(t - t0)/tau). A ramp x = t gives y = t - tau (1 - exp(-t/tau)).
- Window mean on a ramp. The mean of x = t over [t - W, t] is t - W/2.
- Event sample. A sample at an event time reads the post-event value; a sample just before reads the pre-event value; the lag state is continuous across the event.
- Noise. A reading is truth + noise, quantised to a step of span/65535. Its mean is the truth and its variance sigma^2 + step^2/12 (the quantisation noise is not negligible only for the level, where the step 0.27 mm is close to sigma 0.25 mm). The sample mean has standard deviation sqrt(var/N), the sample standard deviation sqrt(var/(2N)).
- Dropout. The count of lost samples is binomial(N, 0.0005).
- Atmosphere. All pressure transmitters are referenced to the site atmosphere, so the same absolute pressure reads (101325 - 94300)/1e5 = 0.07025 bar higher in the coastal stratum than in the inland one; level, flow and temperature do not depend on the stratum.

Independence: the closed forms and binomial/normal sampling bounds are hand derived; the random draws come from the code under test.
