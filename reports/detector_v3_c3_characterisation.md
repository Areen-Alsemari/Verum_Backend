# C3 alone: operating characterisation, residual signatures, feasibility

C3 is the topology residual detector of the plan with the operator-set condition key. C1, C2, C4 and every fusion are dropped. Protocol: section 13 of the experiment plan, committed before this stage was run.

## 1. Summary

- Window level at a 5% window false-alarm target: recall 0.531 (0.475 to 0.589) out of fold and 0.663 (0.573 to 0.745) on validation, 14.47 and 14.71 false alarms per day.
- Policies at a 5% fault-free-episode target, detection rate of faulty episodes (out of fold / validation): 1/1 0.35 / 0.57; 2/3 0.57 / 0.72; 3/5 0.55 / 0.66. False alarms per day out of fold: 2.71, 4.64, 5.9.
- Distinct residual signatures in both sets: pump (R2), drift (R1). Classification differs between the sets for bias, leak; the other types share residuals.
- Runtime: every input except the set conditions and the alarm history is in a summary_v1 request; the fitted model is 93 numbers (3,061 bytes).
- Commanded lineup: not in a request, and not independent of where faults are placed. Nothing was evaluated.

## 2. Operating characterisation

### 2.1 Window level at the reference threshold

Threshold: 95th percentile of fault-free window scores of the other parity fold (5% window false-alarm target).

| set | false-alarm rate | false alarms per day | recall, all faults | AP | matched-stage AUROC |
|---|---|---|---|---|---|
| grouped CV (out of fold, train) | 0.050 (0.045 to 0.056) | 14.47 | 0.531 (0.475 to 0.589) | 0.588 (0.534 to 0.640) | 0.786 (0.751 to 0.820) |
| validation (held-out combinations) | 0.051 (0.044 to 0.058) | 14.71 | 0.663 (0.573 to 0.745) | 0.730 (0.649 to 0.797) | 0.852 (0.800 to 0.896) |

**Recall by fault type:**

| fault type | OOF windows | OOF recall | validation windows | validation recall |
|---|---|---|---|---|
| restriction | 490 | 0.376 (0.290 to 0.467) | 156 | 0.564 (0.407 to 0.710) |
| pump | 69 | 1.000 (1.000 to 1.000) | 72 | 1.000 (1.000 to 1.000) |
| bias | 132 | 0.204 (0.061 to 0.383) | 69 | 0.493 (0.256 to 0.760) |
| drift | 197 | 0.904 (0.827 to 0.965) | 50 | 0.540 (0.267 to 0.826) |
| stuck | 79 | 0.747 (0.567 to 0.908) | 33 | 1.000 (1.000 to 1.000) |
| leak | 146 | 0.363 (0.215 to 0.541) | 57 | 0.614 (0.368 to 0.881) |
| misrouting | 9 | 0.222 (0.167 to 0.333) | 15 | 0.067 (0.000 to 0.167) |
| multi | 131 | 0.710 (0.571 to 0.833) | 44 | 0.886 (0.694 to 1.000) |

### 2.2 Alarm policies (k of the last n windows)

Threshold per policy: the smallest value with at most 5% of fault-free calibration episodes alarming, using the scores of other folds (out of fold) or the out-of-fold train scores (validation). Out of fold there is one threshold per fold. The thresholds were fixed by this rule before any result was seen; all three policies are shown.

**grouped CV (out of fold, train):**

| policy | threshold(s) | fault-free episodes with any alarm | alarm rate on fault-free windows | false alarms per day | faulty episodes detected | delay quartiles (s) | never detected |
|---|---|---|---|---|---|---|---|
| 1/1 | 23.22, 23.22, 19.24, 21.43, 23.86 | 70/1313 (0.053 (0.042 to 0.066)) | 0.009 (0.007 to 0.012) | 2.710 (2.070 to 3.340) | 101/290 (0.348 (0.294 to 0.404)) | 1109 / 1280 / 1598 | 189 |
| 2/3 | 1.83, 1.82, 1.76, 1.84, 1.81 | 67/1313 (0.051 (0.040 to 0.063)) | 0.016 (0.012 to 0.021) | 4.640 (3.400 to 6.080) | 166/290 (0.572 (0.517 to 0.631)) | 1378 / 1574 / 1835 | 124 |
| 3/5 | 1.42, 1.37, 1.36, 1.40, 1.37 | 65/1313 (0.050 (0.037 to 0.061)) | 0.021 (0.015 to 0.027) | 5.900 (4.200 to 7.690) | 159/290 (0.548 (0.493 to 0.604)) | 1651 / 1824 / 2066 | 131 |

**validation (held-out combinations):**

| policy | threshold(s) | fault-free episodes with any alarm | alarm rate on fault-free windows | false alarms per day | faulty episodes detected | delay quartiles (s) | never detected |
|---|---|---|---|---|---|---|---|
| 1/1 | 22.60 | 42/553 (0.076 (0.054 to 0.098)) | 0.015 (0.011 to 0.019) | 4.290 (3.080 to 5.500) | 68/120 (0.567 (0.478 to 0.657)) | 1072 / 1258 / 1980 | 52 |
| 2/3 | 1.82 | 37/553 (0.067 (0.047 to 0.088)) | 0.019 (0.013 to 0.026) | 5.620 (3.860 to 7.520) | 87/120 (0.725 (0.640 to 0.801)) | 1371 / 1525 / 2016 | 33 |
| 3/5 | 1.38 | 35/553 (0.063 (0.044 to 0.084)) | 0.021 (0.014 to 0.028) | 6.050 (3.970 to 8.090) | 79/120 (0.658 (0.570 to 0.748)) | 1661 / 1780 / 1963 | 41 |

**Episode detection rate by fault type** (type of the first faulty window):

*grouped CV (out of fold, train):*

| fault type | episodes | 1/1 | 2/3 | 3/5 |
|---|---|---|---|---|
| restriction | 117 | 0.179 (0.110 to 0.252) | 0.410 (0.325 to 0.500) | 0.419 (0.333 to 0.511) |
| pump | 17 | 1.000 (1.000 to 1.000) | 0.941 (0.809 to 1.000) | 0.882 (0.700 to 1.000) |
| bias | 25 | 0.160 (0.037 to 0.318) | 0.200 (0.050 to 0.370) | 0.200 (0.050 to 0.370) |
| drift | 37 | 0.703 (0.548 to 0.839) | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| stuck | 15 | 0.467 (0.200 to 0.733) | 0.867 (0.667 to 1.000) | 0.800 (0.562 to 1.000) |
| leak | 33 | 0.212 (0.079 to 0.360) | 0.606 (0.433 to 0.769) | 0.545 (0.367 to 0.718) |
| misrouting | 2 | 0.000 (0.000 to 0.000) | 0.000 (0.000 to 0.000) | 0.000 (0.000 to 0.000) |
| multi | 44 | 0.432 (0.283 to 0.578) | 0.614 (0.474 to 0.762) | 0.523 (0.378 to 0.673) |

*validation (held-out combinations):*

| fault type | episodes | 1/1 | 2/3 | 3/5 |
|---|---|---|---|---|
| restriction | 39 | 0.462 (0.290 to 0.615) | 0.615 (0.452 to 0.769) | 0.538 (0.378 to 0.708) |
| pump | 18 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) | 0.944 (0.800 to 1.000) |
| bias | 16 | 0.438 (0.188 to 0.692) | 0.438 (0.188 to 0.692) | 0.438 (0.188 to 0.692) |
| drift | 10 | 0.300 (0.000 to 0.625) | 0.900 (0.667 to 1.000) | 0.900 (0.667 to 1.000) |
| stuck | 6 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| leak | 16 | 0.500 (0.250 to 0.750) | 0.812 (0.600 to 1.000) | 0.562 (0.278 to 0.824) |
| misrouting | 3 | 0.000 (0.000 to 0.000) | 0.333 (0.000 to 1.000) | 0.667 (0.000 to 1.000) |
| multi | 12 | 0.667 (0.375 to 0.917) | 0.750 (0.462 to 1.000) | 0.667 (0.375 to 0.923) |

**Window recall by fault type** (share of faulty windows at which the policy is alarming):

*grouped CV (out of fold, train):*

| fault type | windows | 1/1 | 2/3 | 3/5 |
|---|---|---|---|---|
| restriction | 490 | 0.139 (0.081 to 0.206) | 0.325 (0.254 to 0.404) | 0.261 (0.203 to 0.320) |
| pump | 69 | 1.000 (1.000 to 1.000) | 0.754 (0.695 to 0.795) | 0.522 (0.424 to 0.597) |
| bias | 132 | 0.151 (0.010 to 0.314) | 0.159 (0.040 to 0.306) | 0.129 (0.032 to 0.245) |
| drift | 197 | 0.624 (0.470 to 0.776) | 0.766 (0.717 to 0.806) | 0.594 (0.554 to 0.629) |
| stuck | 79 | 0.506 (0.210 to 0.774) | 0.633 (0.466 to 0.758) | 0.519 (0.386 to 0.621) |
| leak | 146 | 0.199 (0.067 to 0.353) | 0.404 (0.257 to 0.543) | 0.301 (0.191 to 0.408) |
| misrouting | 9 | 0.000 (0.000 to 0.000) | 0.000 (0.000 to 0.000) | 0.000 (0.000 to 0.000) |
| multi | 131 | 0.366 (0.219 to 0.514) | 0.481 (0.376 to 0.583) | 0.275 (0.206 to 0.344) |

*validation (held-out combinations):*

| fault type | windows | 1/1 | 2/3 | 3/5 |
|---|---|---|---|---|
| restriction | 156 | 0.359 (0.211 to 0.515) | 0.506 (0.385 to 0.619) | 0.365 (0.257 to 0.467) |
| pump | 72 | 1.000 (1.000 to 1.000) | 0.750 (0.710 to 0.783) | 0.500 (0.419 to 0.566) |
| bias | 69 | 0.449 (0.193 to 0.733) | 0.348 (0.149 to 0.583) | 0.246 (0.106 to 0.420) |
| drift | 50 | 0.300 (0.000 to 0.638) | 0.640 (0.425 to 0.792) | 0.480 (0.315 to 0.600) |
| stuck | 33 | 0.970 (0.885 to 1.000) | 0.818 (0.773 to 0.853) | 0.636 (0.545 to 0.706) |
| leak | 57 | 0.421 (0.167 to 0.688) | 0.597 (0.431 to 0.724) | 0.351 (0.182 to 0.491) |
| misrouting | 15 | 0.000 (0.000 to 0.000) | 0.133 (0.000 to 0.667) | 0.200 (0.000 to 0.333) |
| multi | 44 | 0.705 (0.375 to 0.974) | 0.682 (0.531 to 0.771) | 0.477 (0.324 to 0.572) |

### 2.3 Controls

| set | shuffle AP | shuffle AUROC | shuffle matched AUROC | placebo matched AUROC | constant columns |
|---|---|---|---|---|---|
| grouped CV (out of fold, train) | 0.128 | 0.500 | 0.500 | 0.499 (0.473 to 0.525) | none |
| validation (held-out combinations) | 0.127 | 0.500 | 0.498 | 0.508 (0.467 to 0.546) | none |

Episode level: the shuffle gives the onsets of the faulty episodes to randomly chosen episodes (200 permutations; mean, 2.5%, 97.5%) and recomputes the detection rate; the placebo is the difference in alarming rate on fault-free windows at positions 1 to 5 between episodes that later contain a faulty window and episodes that never do.

| set | policy | detection rate | shuffled detection rate | placebo difference |
|---|---|---|---|---|
| grouped CV (out of fold, train) | 1/1 | 0.348 (0.294 to 0.404) | 0.099 0.069 0.124 | -0.004 (-0.009 to -0.000) |
| grouped CV (out of fold, train) | 2/3 | 0.572 (0.517 to 0.631) | 0.136 0.103 0.172 | 0.003 (-0.006 to 0.014) |
| grouped CV (out of fold, train) | 3/5 | 0.548 (0.493 to 0.604) | 0.137 0.103 0.169 | -0.006 (-0.014 to 0.004) |
| validation (held-out combinations) | 1/1 | 0.567 (0.478 to 0.657) | 0.140 0.092 0.208 | 0.002 (-0.010 to 0.015) |
| validation (held-out combinations) | 2/3 | 0.725 (0.640 to 0.801) | 0.177 0.117 0.242 | -0.004 (-0.012 to 0.006) |
| validation (held-out combinations) | 3/5 | 0.658 (0.570 to 0.748) | 0.163 0.108 0.225 | -0.007 (-0.012 to -0.003) |

## 3. Residual signature matrix

Each cell is: mean share in the score / fraction of windows in which the residual is the largest / fraction in which it exceeds its own 95th-percentile threshold from fault-free windows the model did not see. `none` is the fraction of windows in which all four residuals are zero (no top contributor). The fault-free row is the reference: its exceed fractions should sit near 0.05.

**grouped CV (out of fold, train):**

| fault type | windows | R1_mass_balance | R2_pump_head | R3_discharge_loss | R4_receipt_line | none |
|---|---|---|---|---|---|---|
| restriction | 490 | 0.09 / 0.07 / 0.01 | 0.18 / 0.18 / 0.13 | 0.23 / 0.24 / 0.21 | 0.35 / 0.35 / 0.27 | 0.16 |
| pump | 69 | 0.00 / 0.00 / 0.00 | 1.00 / 1.00 / 1.00 | 0.00 / 0.00 / 0.13 | 0.00 / 0.00 / 0.00 | 0.00 |
| bias | 132 | 0.19 / 0.19 / 0.07 | 0.13 / 0.12 / 0.12 | 0.16 / 0.17 / 0.14 | 0.27 / 0.27 / 0.05 | 0.25 |
| drift | 197 | 0.94 / 0.96 / 0.96 | 0.02 / 0.01 / 0.05 | 0.02 / 0.02 / 0.11 | 0.02 / 0.00 / 0.06 | 0.01 |
| stuck | 79 | 0.56 / 0.56 / 0.70 | 0.19 / 0.22 / 0.38 | 0.18 / 0.16 / 0.39 | 0.02 / 0.01 / 0.00 | 0.05 |
| leak | 146 | 0.52 / 0.53 / 0.51 | 0.23 / 0.24 / 0.21 | 0.03 / 0.02 / 0.15 | 0.14 / 0.14 / 0.04 | 0.08 |
| misrouting | 9 | 0.15 / 0.11 / 0.11 | 0.09 / 0.00 / 0.11 | 0.42 / 0.56 / 0.22 | 0.00 / 0.00 / 0.00 | 0.33 |
| multi | 131 | 0.41 / 0.42 / 0.47 | 0.25 / 0.26 / 0.29 | 0.18 / 0.19 / 0.25 | 0.13 / 0.09 / 0.14 | 0.04 |
| fault-free | 8579 | 0.21 / 0.21 / 0.05 | 0.19 / 0.20 / 0.05 | 0.15 / 0.16 / 0.05 | 0.19 / 0.18 / 0.05 | 0.25 |

**validation (held-out combinations):**

| fault type | windows | R1_mass_balance | R2_pump_head | R3_discharge_loss | R4_receipt_line | none |
|---|---|---|---|---|---|---|
| restriction | 156 | 0.02 / 0.01 / 0.04 | 0.42 / 0.40 / 0.37 | 0.48 / 0.52 / 0.46 | 0.05 / 0.04 / 0.00 | 0.03 |
| pump | 72 | 0.00 / 0.00 / 0.03 | 1.00 / 1.00 / 1.00 | 0.00 / 0.00 / 0.11 | 0.00 / 0.00 / 0.00 | 0.00 |
| bias | 69 | 0.05 / 0.04 / 0.03 | 0.30 / 0.17 / 0.38 | 0.40 / 0.52 / 0.42 | 0.08 / 0.09 / 0.06 | 0.17 |
| drift | 50 | 0.80 / 0.86 / 0.84 | 0.08 / 0.04 / 0.06 | 0.08 / 0.08 / 0.04 | 0.04 / 0.02 / 0.00 | 0.00 |
| stuck | 33 | 0.38 / 0.39 / 0.76 | 0.34 / 0.45 / 0.70 | 0.28 / 0.15 / 0.67 | 0.00 / 0.00 / 0.00 | 0.00 |
| leak | 57 | 0.44 / 0.46 / 0.75 | 0.41 / 0.40 / 0.47 | 0.11 / 0.11 / 0.32 | 0.00 / 0.00 / 0.00 | 0.04 |
| misrouting | 15 | 0.17 / 0.13 / 0.00 | 0.42 / 0.40 / 0.27 | 0.14 / 0.20 / 0.07 | 0.00 / 0.00 / 0.00 | 0.27 |
| multi | 44 | 0.42 / 0.41 / 0.66 | 0.32 / 0.34 / 0.48 | 0.08 / 0.07 / 0.27 | 0.17 / 0.18 / 0.23 | 0.00 |
| fault-free | 3484 | 0.13 / 0.11 / 0.04 | 0.33 / 0.33 / 0.09 | 0.25 / 0.27 / 0.09 | 0.13 / 0.12 / 0.02 | 0.16 |

**Classification** (rule fixed in the plan: distinct when the largest exceed fraction is at least 0.30 and at least twice the second; none when it is below 0.15; shared otherwise; a type is called distinct only if both sets agree):

| fault type | out of fold | validation | verdict |
|---|---|---|---|
| restriction | shared | shared | shared |
| pump | distinct R2 | distinct R2 | distinct R2 |
| bias | none | shared | disagree |
| drift | distinct R1 | distinct R1 | distinct R1 |
| stuck | shared | shared | shared |
| leak | distinct R1 | shared | disagree |
| misrouting | shared | shared | shared |
| multi | shared | shared | shared |

## 4. Runtime feasibility (read-only)

### 4.1 Inputs of C3 against an Agent 2 request

| tag(s) | quantity | used by | carried by a request |
|---|---|---|---|
| FT-001, FT-201 | window `mean` | R1 mass balance | yes, summary_v1 signal field |
| LT-101, LT-102, LT-103 | window `slope_per_s` | R1 storage term | yes, summary_v1 signal field |
| PT-001 and FT-001 `mean` | window `mean` | R4 receipt line | yes, summary_v1 signal field |
| PT-201, PT-202A, PT-202B, PT-203 | window `mean` | R2 pump head, R3 discharge loss | yes, summary_v1 signal field |
| P-101A, P-101B | `latest_value` (observed run state) | pump-state selector of R2, R3 | yes, boolean signal |
| atmosphere, temperature set point, flow set point | episode conditions | selects the R4 fit by regime | no |
| fitted coefficients and scales | constants | all residuals | no, a pinned file |
| alarm thresholds | constants | all policies | no, a pinned file |
| scores of the previous windows | history | 2/3 and 3/5 policies | no |

Not used by C3: raw 300 s rows (the `sequence_v1` representation), arrival ages, row and sample counts, quality flags, minimum and maximum, standard deviation. The CUSUM of the first experiment used raw rows; C3 does not.

- The contract request holds the same 30 summary signals as the role-view records the results were computed on, with the same fields; the request input is the observation summary and a forecast report, nothing else.
- The Agent 2 code reads `input.observations.summary.signals` only, so it handles `summary_v1` and not `sequence_v1`. C3 needs `summary_v1`.
- The summary mean and slope are computed over all measured samples of the window, including samples flagged suspect or bad (an example request shows a minimum of 0.11 beside a mean of 594.8). C3 reads them as they are, in every result above, and applies no quality screening. A missing statistic counts as no evidence.
- C3 needs 12 of the 30 tags. The existing coverage gate of the forest (90% of the 30 tags) is not a gate for C3; which tags must be usable is a design decision that this work does not make.
- **Missing from a request:** the set conditions, and the history of earlier scores. 13 of the 22 fits are per set-condition regime (R4); without the conditions a request can only use the pooled R4 fit, the same fallback that already served 74.0% of validation windows under the new key (validation AP of C3 was 0.739 with the old key and 0.730 with the new one; `reports/detector_v2_results.md`, section 2.3). That is not a test of a pooled-only R4 and is not claimed as one. The k-of-n policies need the scores of the last n-1 windows of the same episode, which a single-window request does not carry; they need stored state or a request that attaches earlier windows.

### 4.2 Pinned parameter file and the tag-to-location mapping

The fitted model holds 93 numbers in 22 fits (R2 4, R3 4, R4 14) plus the mass-balance coefficients: 3,061 bytes as JSON, plus one threshold per policy. It fits in a small pinned file, with the tag-to-role mapping written in the same file.

How the mapping is derived: the declared reference gives 28 connections forming one line (receipt meter, receipt header, three tank branches, suction header, two pump branches, discharge header, delivery meter) and lists the 30 instruments with unit and sampling only. It gives no instrument location; the pressure transmitters appear as assets and in no connection. The mapping is therefore taken from the tag names: FT-001 receipt meter, FT-201 delivery meter, LT-10i tank TK-10i, PT-001 receipt line, PT-201 suction header, PT-202A and PT-202B discharge of pumps P-101A and P-101B, PT-203 discharge header.

What the data support: the fitted tank areas are 705.05, 705.51 and 705.58 m2 against 706.86 m2 from the declared 30 m diameter, within 0.3%. That supports the level tags as tank inventory and the sign convention of FT-001 as inflow and FT-201 as outflow in R1. It does not tell the three tanks apart, since they are identical.

What is unverified: that PT-201 sits on the suction header and PT-203 on the discharge header; that PT-202A belongs to pump A and PT-202B to pump B; that the pump-head and loss curves (empirical quadratic fits per pump state, valid inside the operating range seen in training) correspond to physical quantities. The reference carries no pump curve to compare with. These residuals are fitted to simulator data, so a good score is not independent validation.

## 5. Commanded-lineup feasibility (read-only, nothing evaluated)

### 5.1 Is the commanded state in a request?

No. A request carries 30 observed signals. Eleven of them are valve contact states (`XV-*`), two are pump run states and three are level switches; all are what the plant reports, not what was commanded. No field of the request, of the contract or of the declared reference is named or described as a commanded state, lineup or set point. The commanded operating mode (for example `RECEIVE_101_DELIVER_102_A`) exists in the episode label file, which holds the campaign strata and is not available to an agent. The reference also declares the limit `contact_is_not_true_valve_position`: a contact state is not the true valve position.

### 5.2 Is it independent of the injected fault?

No, in two ways. The observed contact states change with some faults (restriction with visible position and misrouting act on valve positions; the regime audit in `reports/detector_v2_regime_audit.md` shows it). The commanded mode is a campaign stratum, and the faults are not placed independently of it: among 2,276 episodes with eligible windows the association of mode with the valve a fault is on is Cramer's V 0.349, and with having any fault 0.111. For example, in mode `RECEIVE_101`, valve `XV-R101` carries 46 of the 93 valve faults. The mode `RECEIVE_101_102` does not appear among the episodes with an eligible window.

| commanded mode | episodes | episodes with a fault | most frequent faulty valves |
|---|---|---|---|
| DELIVER_101_A | 123 | 94 | XV-S101 11, XV-PAO 8, XV-PBI 6 |
| DELIVER_101_B | 149 | 118 | XV-PBO 12, XV-S101 11, XV-PBI 9 |
| DELIVER_102_A | 118 | 87 | XV-PAI 8, XV-S102 5, XV-R101 5 |
| DELIVER_102_B | 160 | 135 | XV-PBO 18, XV-S102 15, XV-PBI 10 |
| DELIVER_103_A | 143 | 103 | XV-S103 18, XV-PAO 10, XV-PAI 8 |
| DELIVER_103_B | 159 | 125 | XV-S103 17, XV-PBO 11, XV-PBI 10 |
| RECEIVE_101 | 261 | 196 | XV-R101 46, XV-R103 11, XV-PAO 10 |
| RECEIVE_101_DELIVER_101_A | 363 | 306 | XV-R101 82, XV-PBI 26, XV-PAO 24 |
| RECEIVE_101_DELIVER_102_A | 329 | 275 | XV-R101 65, XV-PBI 29, XV-S102 28 |
| RECEIVE_102 | 228 | 166 | XV-R102 21, XV-R101 13, XV-PAO 8 |
| RECEIVE_103 | 243 | 186 | XV-R103 24, XV-R101 14, XV-PBO 12 |

### 5.3 How a commanded-against-observed check would be defined

For each valve v in the lineup, the commanded state c_v(t) is open or closed according to the active mode, and the observed state o_v(t) is the contact `latest_value` in the window. The mismatch is m_v(t) = 1 when o_v differs from c_v. The window evidence is the set of mismatched valves, with a debounce (for example the k-of-n rule above) and with windows inside a stated valve travel time after a commanded change excluded. It would act on the 11 valve contacts and nothing else.

### 5.4 What could make it leak the label

- If the commanded state is taken from the label file (the mode stratum), it is truth side information, and the check would be using the campaign design, not an input.
- If it is reconstructed from the observed states of the same episode (for instance the most common state), the fault contaminates the reference it is compared with.
- For misrouting and for restriction with a visible position, the fault is defined as a valve not in its commanded state. The check would then restate the label, and a high recall on those two types would be by construction and not a detection result.
- A valve fault that leaves the contact unchanged (restriction by obstruction) cannot be seen by the check at all.
- Mode is associated with where faults are placed (Cramer's V above), so a model fed the mode can learn the campaign's placement prior.
- A contact that disagrees with the true position (the declared limit) would produce mismatches without a process fault, and valve travel after a commanded change would produce them in the switch-type episodes.

Not evaluated: no model was run and no recall or false-alarm number is given for it.

## 6. Reading the numbers

- Calibration does not transfer fully to validation: the share of fault-free validation episodes with an alarm is 0.076, 0.067 and 0.063 for the three policies against the 0.05 target; the interval of the 1/1 policy lies above 0.05. Out of fold the shares sit at the target.
- The same shift shows in the signature matrix: on validation, fault-free windows exceed the thresholds of R2 and R3 about 9% of the time against 5% by construction.
- Episodes have 2 to 12 eligible windows, median 5. A policy that needs three exceedances (3/5) cannot alarm in an episode with fewer than three eligible windows, and the delay of any policy is bounded by the 300 s grid.
- A k-of-n policy needs k exceedances in the last n windows, so its window recall is lower than 1/1 at the first faulty windows of an episode even when the episode detection rate is higher (pump faults: window recall 1.00 for 1/1 and lower for 2/3 and 3/5, episode detection about 0.9 or more for all).
- The episode-level placebo differences are close to zero. The one interval that excludes zero (validation, 3/5) is negative: episodes that later contain a fault alarm slightly less at positions 1 to 5, which is not the direction of a leak.
- Detection means alarming at one or more faulty-labelled windows of the episode. A false alarm before the onset in a faulty episode is counted in the window alarm rate of fault-free windows, not in the fault-free episode count.
- The signature matrix is descriptive. Misrouting has 9 train and 15 validation windows (2 and 3 episodes); its row cannot support a conclusion.
- Thresholds for the out-of-fold evaluation use the out-of-fold scores of the other folds; those scores come from models whose fit data included the evaluated fold's fault-free windows. Only fault-free scores are used and no label of the evaluated fold, but it is not a fully nested calibration.
- C3 is fitted to simulator data and its parts are empirical fits; tests of a reduced model are not independent validation. The test split was not opened.

## 7. Deviations from the plan

- Parts 3 and 4 were registered as read-only. Two small computations support them and evaluate nothing: C3 was fitted once on all fault-free train windows to count its parameters and compare the tank areas with the declared geometry, and the label files of train and validation episodes were tabulated by commanded mode. Both go through the same audit hook; no score of a held-out window was computed for them.
- The window-level reference, shuffle and placebo of the C3 score reuse the evaluation code of the second stage unchanged.
- Nothing was tuned on the signature matrix or on the policy results.
