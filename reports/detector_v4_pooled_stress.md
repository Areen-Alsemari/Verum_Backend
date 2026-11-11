# Pooled R4, minimal inputs, stress test

C3 alone, as in the C3 report. Protocol: section 14 of the experiment plan, committed before this stage was run.

## 1. Summary

- Pooled R4 (no set conditions) against the per-regime R4: AP difference -0.001 (-0.004 to 0.001) out of fold and 0.000 (-0.001 to 0.001) on validation; matched-stage AUROC difference -0.002 (-0.007 to 0.002) and 0.000 (-0.003 to 0.003).
- The pooled version reads 12 fields, all in a `summary_v1` request; scores do not change when anything else changes, including the regime key, the order and the other windows (largest change 0.0).
- Out of fold, one missing tag takes AP from 0.586 to 0.456 and three to 0.246, with 69% of windows still scorable.
- A deployed Agent 2 can state window-level residual evidence, not a leak, an episode or health (section 5).

## 2. Pooled R4 against the per-regime version

Same folds, same fits for R1 to R3, same thresholds. Pooled R4 is one quadratic of PT-001 on FT-001 mean for all windows; the set conditions are not read.

| set | version | AP | matched-stage AUROC | FAR at 5% target | recall |
|---|---|---|---|---|---|
| grouped CV (out of fold, train) | per-regime R4 | 0.588 (0.534 to 0.640) | 0.786 (0.751 to 0.820) | 0.050 (0.045 to 0.056) | 0.531 (0.475 to 0.589) |
| grouped CV (out of fold, train) | pooled R4 | 0.586 (0.533 to 0.638) | 0.783 (0.749 to 0.819) | 0.050 (0.045 to 0.055) | 0.528 (0.473 to 0.586) |
| grouped CV (out of fold, train) | pooled minus per-regime | -0.001 (-0.004 to 0.001) | -0.002 (-0.007 to 0.002) |  |  |
| validation (held-out combinations) | per-regime R4 | 0.730 (0.649 to 0.797) | 0.852 (0.800 to 0.896) | 0.051 (0.044 to 0.058) | 0.663 (0.573 to 0.745) |
| validation (held-out combinations) | pooled R4 | 0.730 (0.649 to 0.797) | 0.852 (0.801 to 0.896) | 0.051 (0.044 to 0.058) | 0.663 (0.573 to 0.745) |
| validation (held-out combinations) | pooled minus per-regime | 0.000 (-0.001 to 0.001) | 0.000 (-0.003 to 0.003) |  |  |

**Recall by fault type at the 5% window target, grouped CV (out of fold, train):**

| fault type | windows | per-regime | pooled |
|---|---|---|---|
| restriction | 490 | 0.376 (0.290 to 0.467) | 0.367 (0.281 to 0.460) |
| pump | 69 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| bias | 132 | 0.204 (0.061 to 0.383) | 0.204 (0.061 to 0.383) |
| drift | 197 | 0.904 (0.827 to 0.965) | 0.904 (0.827 to 0.965) |
| stuck | 79 | 0.747 (0.567 to 0.908) | 0.747 (0.567 to 0.908) |
| leak | 146 | 0.363 (0.215 to 0.541) | 0.363 (0.215 to 0.541) |
| misrouting | 9 | 0.222 (0.167 to 0.333) | 0.222 (0.167 to 0.333) |
| multi | 131 | 0.710 (0.571 to 0.833) | 0.718 (0.588 to 0.838) |

**Recall by fault type at the 5% window target, validation (held-out combinations):**

| fault type | windows | per-regime | pooled |
|---|---|---|---|
| restriction | 156 | 0.564 (0.407 to 0.710) | 0.564 (0.407 to 0.710) |
| pump | 72 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| bias | 69 | 0.493 (0.256 to 0.760) | 0.493 (0.256 to 0.760) |
| drift | 50 | 0.540 (0.267 to 0.826) | 0.540 (0.267 to 0.826) |
| stuck | 33 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| leak | 57 | 0.614 (0.368 to 0.881) | 0.614 (0.368 to 0.881) |
| misrouting | 15 | 0.067 (0.000 to 0.167) | 0.067 (0.000 to 0.167) |
| multi | 44 | 0.886 (0.694 to 1.000) | 0.886 (0.694 to 1.000) |

**Alarm policies, grouped CV (out of fold, train):**

| policy | version | fault-free episodes alarmed | false alarms per day | faulty episodes detected | median delay (s) | never detected |
|---|---|---|---|---|---|---|
| 1/1 | per-regime | 0.053 | 2.71 | 0.348 (0.294 to 0.404) | 1280 | 189 |
| 1/1 | pooled | 0.053 | 2.71 | 0.348 (0.294 to 0.404) | 1280 | 189 |
| 2/3 | per-regime | 0.051 | 4.64 | 0.572 (0.517 to 0.631) | 1574 | 124 |
| 2/3 | pooled | 0.048 | 3.77 | 0.579 (0.522 to 0.641) | 1562 | 122 |
| 3/5 | per-regime | 0.050 | 5.9 | 0.548 (0.493 to 0.604) | 1824 | 131 |
| 3/5 | pooled | 0.050 | 5.88 | 0.545 (0.489 to 0.600) | 1838 | 132 |

**Alarm policies, validation (held-out combinations):**

| policy | version | fault-free episodes alarmed | false alarms per day | faulty episodes detected | median delay (s) | never detected |
|---|---|---|---|---|---|---|
| 1/1 | per-regime | 0.076 | 4.29 | 0.567 (0.478 to 0.657) | 1258 | 52 |
| 1/1 | pooled | 0.076 | 4.29 | 0.567 (0.478 to 0.657) | 1258 | 52 |
| 2/3 | per-regime | 0.067 | 5.62 | 0.725 (0.640 to 0.801) | 1525 | 33 |
| 2/3 | pooled | 0.076 | 6.19 | 0.725 (0.640 to 0.801) | 1519 | 33 |
| 3/5 | per-regime | 0.063 | 6.05 | 0.658 (0.570 to 0.748) | 1780 | 41 |
| 3/5 | pooled | 0.069 | 6.77 | 0.658 (0.570 to 0.748) | 1780 | 41 |

**Controls of the pooled version** (window shuffle: AP / AUROC / matched; placebo: matched AUROC at positions 1 to 5; episode shuffle detection rate: mean 2.5% 97.5%; episode placebo: rate difference):

| set | window shuffle | window placebo | episode shuffle | episode placebo |
|---|---|---|---|---|
| grouped CV (out of fold, train) | 0.128 / 0.499 / 0.500 | 0.501 (0.476 to 0.527) | 1/1: 0.099 0.069 0.124; 2/3: 0.136 0.103 0.172; 3/5: 0.137 0.100 0.169 | 1/1: -0.004 (-0.009 to -0.000); 2/3: 0.010 (0.001 to 0.022); 3/5: -0.004 (-0.011 to 0.006) |
| validation (held-out combinations) | 0.127 / 0.501 / 0.498 | 0.511 (0.472 to 0.549) | 1/1: 0.140 0.092 0.208; 2/3: 0.185 0.125 0.250; 3/5: 0.168 0.117 0.225 | 1/1: 0.002 (-0.010 to 0.015); 2/3: -0.004 (-0.014 to 0.006); 3/5: -0.005 (-0.011 to 0.002) |

The residual signature classification of section 3 of the C3 report is unchanged with pooled R4.

## 3. Minimal-input check

The pooled C3 reads 12 fields. The contract example request (representation `summary_v1`) carries all of them with the expected unit: fields present True, units match True.

| tag | summary field | unit in the request | present with a value |
|---|---|---|---|
| FT-001 | mean | m3/h | yes |
| FT-201 | mean | m3/h | yes |
| LT-101 | slope_per_s | m | yes |
| LT-102 | slope_per_s | m | yes |
| LT-103 | slope_per_s | m | yes |
| PT-001 | mean | barg | yes |
| PT-201 | mean | barg | yes |
| PT-202A | mean | barg | yes |
| PT-202B | mean | barg | yes |
| PT-203 | mean | barg | yes |
| P-101A | latest_value | bool | yes |
| P-101B | latest_value | bool | yes |

Perturbation tests on the validation windows (largest absolute change of any score):

| perturbation | largest change |
|---|---|
| other statistics overwritten | 0.0 |
| regime and order scrambled | 0.0 |
| window scored alone | 0.0 |

The three perturbations are: every other statistic overwritten by 12345; the regime key set to arbitrary values and the order of the windows shuffled; each of the first 100 windows scored alone. A change of exactly 0.0 means the scores depend on the twelve fields and on nothing else: no set condition, no earlier window, no other window of the set. The 1/1 window-level version therefore needs one `summary_v1` window and the pinned parameters. Scoring the example request itself gives 0.7067 with residuals R1 to R4 [0.1697, 0.0, 0.0, 0.7067].

## 4. Stress test

Nothing is refitted or tuned. The models are those of the folds and of the validation fit; the threshold is the clean one of the same set (OOF [3.1538, 2.9178], validation [6.7428, 6.5105] for the two parity folds) and is applied unchanged to the perturbed scores. Unknown evidence is neither zero nor healthy: a residual with an unknown input drops out, and a window with no residual left cannot be scored, counts as not alarmed and ranks last. One seeded draw per setting; intervals are bootstrap over episodes. Definitions are in section 14.3 of the plan.

**grouped CV (out of fold, train):**

| setting | AP | matched-stage AUROC | false-alarm rate | recall | windows scorable | faulty windows scorable |
|---|---|---|---|---|---|---|
| no perturbation | 0.586 (0.533 to 0.638) | 0.783 (0.749 to 0.819) | 0.050 (0.045 to 0.055) | 0.528 (0.473 to 0.586) | 1.000 | 1.000 |
| 1 tag missing | 0.456 (0.410 to 0.500) | 0.686 (0.654 to 0.716) | 0.033 (0.029 to 0.037) | 0.361 (0.316 to 0.406) | 0.966 | 0.962 |
| 2 tags missing | 0.338 (0.300 to 0.375) | 0.612 (0.583 to 0.639) | 0.019 (0.017 to 0.023) | 0.223 (0.190 to 0.258) | 0.853 | 0.857 |
| 3 tags missing | 0.246 (0.215 to 0.277) | 0.557 (0.531 to 0.579) | 0.010 (0.008 to 0.012) | 0.113 (0.091 to 0.138) | 0.691 | 0.696 |
| noise 1x | 0.431 (0.376 to 0.487) | 0.674 (0.634 to 0.713) | 0.518 (0.495 to 0.541) | 0.708 (0.662 to 0.756) | 1.000 | 1.000 |
| noise 2x | 0.367 (0.316 to 0.420) | 0.637 (0.594 to 0.677) | 0.723 (0.706 to 0.740) | 0.807 (0.769 to 0.842) | 1.000 | 1.000 |
| noise 3x | 0.336 (0.285 to 0.389) | 0.615 (0.572 to 0.656) | 0.830 (0.817 to 0.843) | 0.877 (0.849 to 0.903) | 1.000 | 1.000 |

**validation (held-out combinations):**

| setting | AP | matched-stage AUROC | false-alarm rate | recall | windows scorable | faulty windows scorable |
|---|---|---|---|---|---|---|
| no perturbation | 0.730 (0.649 to 0.797) | 0.852 (0.801 to 0.896) | 0.051 (0.044 to 0.058) | 0.663 (0.573 to 0.745) | 1.000 | 1.000 |
| 1 tag missing | 0.522 (0.457 to 0.578) | 0.711 (0.668 to 0.752) | 0.033 (0.028 to 0.039) | 0.415 (0.342 to 0.478) | 0.993 | 0.998 |
| 2 tags missing | 0.389 (0.329 to 0.448) | 0.618 (0.573 to 0.658) | 0.017 (0.013 to 0.021) | 0.260 (0.205 to 0.315) | 0.907 | 0.927 |
| 3 tags missing | 0.266 (0.221 to 0.309) | 0.549 (0.511 to 0.586) | 0.011 (0.007 to 0.014) | 0.131 (0.097 to 0.164) | 0.751 | 0.776 |
| noise 1x | 0.602 (0.511 to 0.686) | 0.757 (0.701 to 0.813) | 0.610 (0.585 to 0.632) | 0.841 (0.793 to 0.885) | 1.000 | 1.000 |
| noise 2x | 0.576 (0.488 to 0.660) | 0.759 (0.703 to 0.814) | 0.788 (0.763 to 0.811) | 0.907 (0.862 to 0.949) | 1.000 | 1.000 |
| noise 3x | 0.522 (0.431 to 0.602) | 0.723 (0.665 to 0.778) | 0.876 (0.853 to 0.895) | 0.944 (0.909 to 0.974) | 1.000 | 1.000 |

Reading:

- Missing tags lower recall and the false-alarm rate together, because fewer residuals enter the maximum. AP and matched-stage AUROC fall steadily with each missing tag.
- Noise raises the false-alarm rate a great deal at the fixed threshold: noise on all ten inputs at once adds up in every residual, so the clean threshold is far too low for noisy windows. Recall rises for the same reason. The ranking measures (AP, matched AUROC) show the loss of discrimination without the threshold.
- Unscorable windows appear only when every residual is lost. R2 and R3 apply only while a pump runs; windows with no pump running (train 45.6%, validation 9.4%) have R1 and R4 only, which read seven of the twelve inputs. That is why the scorable share is lower out of fold than on validation.
- The noise scale is defined per input from the fault-free residual scale (plan section 14.3). It is a realism check, not an estimate of the real sensor noise, which this work does not know.

## 5. What a deployed Agent 2 can claim

**Window-level evidence only.** For one `summary_v1` window the pooled C3 gives a score and four residuals. The statement it supports is: this window's residuals exceed what fault-free windows of the grouped-CV folds show, by this much, in these residuals. It does not give an episode, an onset, a fault identity or a location, and a window without an alarm is not evidence of health (recall at the 5% window target is about 0.5 out of fold and 0.66 on validation, and below 0.4 for restriction, leak, bias and misrouting out of fold).

**A fixed threshold does not carry over unchanged.** The 95th percentile of the out-of-fold fault-free scores is 3.03. Applied to validation it gives a false-alarm rate of 0.080 and a recall of 0.740, against the 0.05 target by construction in each set separately. The threshold needs to be set and monitored on the data the agent will see.

**The alarm policy needs history.** The 1/1 window-level version needs one request. The 2/3 and 3/5 policies, which detected more faulty episodes at the same fault-free-episode target (section 2), need the scores of the previous windows of the same episode, which a single-window request does not carry. Without stored state the agent can only state window-level evidence.

**Residual-level statements supported by the signature matrix** (descriptive, small numbers for some types):

- Pump: R2 exceeds its own threshold in 1.00 of pump-fault windows out of fold and 1.00 on validation, R3 in 0.13 and 0.11, R1 and R4 in at most 0.03. R2 without R3 supports a loss of pump head. R2 with R3 together also occurs for faults of PT-202A or FT-201 (table below), so R2 alone is not exclusive to the pump.
- Drift: R1 exceeds in 0.96 of drift windows out of fold and 0.84 on validation. In the single-fault episodes the drifting tag is FT-001 or a tank level (table below).
- Leak: R1 exceeds in 0.51 out of fold and 0.75 on validation, and R2 in 0.21 and 0.47; the two sets disagree on whether R1 is distinct for leaks.

**Leak against flow-meter error.** R1 is the mismatch between the receipt flow, the delivery flow and the change of tank inventory from the level slopes. A leak between the meters produces such a mismatch. So does a bias, drift or stuck value of FT-001 or FT-201, and so does a drifting level sensor (table below: R1 exceeds in 0.69 to 1.00 of those windows out of fold). R1 alone therefore cannot separate a leak from a flow-meter or level-sensor fault. The sign of the residual, which this work does not use (z is an absolute value) and has not tested, and evidence from other tags or from an inspection would be needed for that. Agent 2 should report a mass imbalance and name the leak and the instrument faults as candidates, not a leak.

**Not claimable:** restriction, misrouting, stuck values and multi-component faults share residuals, and bias has no signature out of fold and a shared one on validation (registered classification, section 3 of the C3 report); misrouting has 9 and 15 windows. R4 is distinct for no fault type. Pressure-sensor faults show partly in R2 and R3 (table below) but not consistently across the two sets.

| set | fault | faulty tag | windows | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|---|---|
| oof | bias | FT-001 | 10 | 0.80 | 0.00 | 0.00 | 0.00 |
| oof | bias | LT-102 | 10 | 0.10 | 0.10 | 0.10 | 0.00 |
| oof | bias | LT-103 | 24 | 0.00 | 0.04 | 0.12 | 0.00 |
| oof | bias | PT-001 | 9 | 0.00 | 0.00 | 0.00 | 0.00 |
| oof | bias | PT-201 | 29 | 0.00 | 0.21 | 0.03 | 0.00 |
| oof | bias | PT-202B | 21 | 0.00 | 0.29 | 0.29 | 0.00 |
| oof | bias | PT-203 | 16 | 0.00 | 0.06 | 0.44 | 0.00 |
| oof | drift | FT-001 | 40 | 0.82 | 0.03 | 0.05 | 0.07 |
| oof | drift | LT-101 | 65 | 1.00 | 0.02 | 0.05 | 0.11 |
| oof | drift | LT-102 | 54 | 1.00 | 0.07 | 0.17 | 0.11 |
| oof | drift | LT-103 | 38 | 1.00 | 0.08 | 0.18 | 0.00 |
| oof | stuck | FT-001 | 39 | 0.69 | 0.00 | 0.00 | 0.00 |
| oof | stuck | FT-201 | 17 | 1.00 | 1.00 | 1.00 | 0.00 |
| oof | stuck | LT-102 | 10 | 1.00 | 0.00 | 0.10 | 0.00 |
| oof | stuck | PT-202A | 13 | 0.08 | 1.00 | 1.00 | 0.00 |
| val | bias | LT-102 | 15 | 0.13 | 0.20 | 0.20 | 0.00 |
| val | bias | PT-202A | 17 | 0.00 | 0.71 | 0.71 | 0.00 |
| val | bias | PT-202B | 11 | 0.00 | 0.36 | 0.36 | 0.00 |
| val | bias | PT-203 | 9 | 0.00 | 0.11 | 1.00 | 0.00 |
| val | drift | FT-001 | 31 | 0.74 | 0.03 | 0.03 | 0.00 |
| val | drift | LT-103 | 14 | 1.00 | 0.14 | 0.07 | 0.00 |
| val | stuck | FT-201 | 15 | 0.80 | 1.00 | 1.00 | 0.00 |

The table is a descriptive check made for this section, not part of the registered classification: fraction of single-fault sensor-fault windows in which each residual exceeds its own threshold, by faulty tag, for tags with at least 8 windows.

The statements depend on the tag-to-location mapping taken from tag names, parts of which are unverified (section 4.2 of the C3 report), and on simulator data.

## 6. Limits and deviations

- Pooled R4 is compared on the same windows and folds as the per-regime version. The per-regime scores are those saved in the C3 stage; the pooled run reproduces every other part of C3 exactly.
- The stress test uses one random draw per setting. The intervals are over episodes and do not include the variation between draws.
- The noise scales come from the fitted residual scales (plan section 14.3), and missing tags are drawn uniformly. Real sensor failures are not uniform and are correlated across tags.
- The per-asset table was added in the report and was named in the plan (section 14.4) as a descriptive check; nothing was tuned on it.
- The contract example request is a fixture; scoring it shows that the fields are readable, not that its values are plant values.
- The test split was not opened; the audit hook recorded no rejected attempt.
