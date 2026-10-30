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
