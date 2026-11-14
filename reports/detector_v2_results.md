# Detector experiment, second stage

Regime key and four enhancements under grouped cross-validation. The protocol is in sections 11 and 12 of the plan, committed before the runs it governs. Validation is reported separately as the held-out-combination benchmark and decides nothing.

## 1. Summary

- The key of the first experiment contained fault effects for restriction and misrouting. With operator-set conditions as the key, C3 is unchanged on validation (AP 0.730) while the fused score C4 falls from 0.887 to 0.290 and the 5% threshold gives no alarm (section 2.3).
- Grouped CV, 22 units, 9,832 windows, 1,253 faulty (prevalence 0.127): the baseline system has AP 0.305 (0.257 to 0.360).
- Kept by the stop rule: E1, E1+E4. Dropped: E1+E2, E1+E3. Final system E1+E4: AP 0.415 (0.357 to 0.475), matched-stage AUROC 0.728 (0.690 to 0.765).
- C3 alone has AP 0.588 (0.534 to 0.640), above every fusion; the per-tag baseline and PCA components stay at chance level in every system (section 4).
- On validation, the final system alarms at the 5% target with false-alarm rate 0.050 (0.043 to 0.058) and recall 0.558 (0.463 to 0.647); the systems before E4 give no alarm at all there (saturated fusion score).

## 2. Phase A: the regime key

### 2.1 What the old key contained

The key behind the 200-window guard and the per-regime baselines was the latest state of 16 on/off tags: three level switches, the two pump run states and eleven valve contact states. Restriction and misrouting act on valve positions, so the key of such a window differs from every fault-free key because of the fault. Train windows with a key that no fault-free train window has: restriction 405 of 490, misrouting 9 of 9; validation: restriction 155 of 156, misrouting 15 of 15. The full table, with the tags that differ, is in `reports/detector_v2_regime_audit.md`.

### 2.2 Correction of Amendment 1

Train does contain 40 degrees C: 203 episodes, of which 171 have eligible windows, with 1,010 fault-free eligible windows. The shift is in the mixture: 54% of the fault-free train windows are at 25 degrees C and no eligible validation window is; 55% of the fault-free validation windows are at 40 degrees C against 12% of the fault-free train windows.

### 2.3 Re-run of C3 and C4 with the new key (Amendment 2)

Validation windows, same fitted constants, thresholds and cross-fitting as before; only the key changed. The old-key rows are the first experiment, reproduced exactly (all score arrays identical). Intervals are 95% bootstrap over episodes. C1 and C2 are shown because they feed C4; the requested comparison is C3 and C4.

Validation windows in a regime without an own baseline: 5.0% with the old key, 74.0% with the new key.

| model | metric | old key | new key | change |
|---|---|---|---|---|
| C1 | AP | 0.155 (0.122 to 0.188) | 0.142 (0.115 to 0.177) | -0.013 |
| C1 | AUROC | 0.536 (0.489 to 0.582) | 0.539 (0.494 to 0.586) | +0.003 |
| C1 | matched AUROC | 0.549 (0.479 to 0.614) | 0.537 (0.472 to 0.603) | -0.012 |
| C1 | FAR at 5% target | 0.048 (0.035 to 0.062) | 0.052 (0.042 to 0.064) | +0.005 |
| C1 | recall, all faults | 0.050 (0.026 to 0.078) | 0.059 (0.038 to 0.081) | +0.008 |
| C2a | AP | 0.427 (0.339 to 0.509) | 0.148 (0.117 to 0.186) | -0.280 |
| C2a | AUROC | 0.723 (0.674 to 0.774) | 0.550 (0.497 to 0.601) | -0.173 |
| C2a | matched AUROC | 0.698 (0.640 to 0.750) | 0.543 (0.477 to 0.609) | -0.154 |
| C2a | FAR at 5% target | 0.046 (0.039 to 0.054) | 0.051 (0.036 to 0.068) | +0.005 |
| C2a | recall, all faults | 0.359 (0.275 to 0.446) | 0.059 (0.032 to 0.092) | -0.300 |
| C2b | AP | 0.648 (0.559 to 0.726) | 0.134 (0.106 to 0.171) | -0.514 |
| C2b | AUROC | 0.771 (0.715 to 0.825) | 0.529 (0.477 to 0.583) | -0.242 |
| C2b | matched AUROC | 0.777 (0.719 to 0.831) | 0.521 (0.451 to 0.596) | -0.256 |
| C2b | FAR at 5% target | 0.053 (0.045 to 0.062) | 0.046 (0.029 to 0.063) | -0.007 |
| C2b | recall, all faults | 0.556 (0.463 to 0.644) | 0.060 (0.024 to 0.108) | -0.496 |
| C3 | AP | 0.739 (0.661 to 0.806) | 0.730 (0.649 to 0.797) | -0.009 |
| C3 | AUROC | 0.860 (0.811 to 0.904) | 0.859 (0.810 to 0.902) | -0.000 |
| C3 | matched AUROC | 0.852 (0.801 to 0.899) | 0.852 (0.800 to 0.896) | -0.000 |
| C3 | FAR at 5% target | 0.051 (0.044 to 0.058) | 0.051 (0.044 to 0.058) | +0.000 |
| C3 | recall, all faults | 0.679 (0.592 to 0.758) | 0.663 (0.573 to 0.745) | -0.016 |
| C4 | AP | 0.887 (0.835 to 0.932) | 0.290 (0.231 to 0.355) | -0.597 |
| C4 | AUROC | 0.943 (0.908 to 0.970) | 0.776 (0.727 to 0.821) | -0.166 |
| C4 | matched AUROC | 0.940 (0.906 to 0.968) | 0.778 (0.712 to 0.837) | -0.162 |
| C4 | FAR at 5% target | 0.049 (0.041 to 0.058) | 0.000 (0.000 to 0.000) | -0.049 |
| C4 | recall, all faults | 0.839 (0.765 to 0.905) | 0.000 (0.000 to 0.000) | -0.839 |
| C1s | AP | 0.179 (0.143 to 0.216) | 0.146 (0.116 to 0.183) | -0.034 |
| C1s | AUROC | 0.624 (0.584 to 0.668) | 0.551 (0.503 to 0.601) | -0.073 |
| C1s | matched AUROC | 0.628 (0.571 to 0.692) | 0.557 (0.493 to 0.623) | -0.071 |
| C1s | FAR at 5% target | 0.047 (0.034 to 0.061) | 0.049 (0.038 to 0.061) | +0.003 |
| C1s | recall, all faults | 0.046 (0.023 to 0.074) | 0.057 (0.035 to 0.081) | +0.010 |
| C2as | AP | 0.591 (0.506 to 0.674) | 0.147 (0.115 to 0.185) | -0.444 |
| C2as | AUROC | 0.773 (0.720 to 0.823) | 0.545 (0.495 to 0.594) | -0.228 |
| C2as | matched AUROC | 0.754 (0.698 to 0.808) | 0.533 (0.469 to 0.595) | -0.222 |
| C2as | FAR at 5% target | 0.046 (0.039 to 0.054) | 0.051 (0.036 to 0.068) | +0.005 |
| C2as | recall, all faults | 0.500 (0.412 to 0.598) | 0.059 (0.032 to 0.092) | -0.442 |
| C2bs | AP | 0.645 (0.558 to 0.725) | 0.138 (0.109 to 0.174) | -0.507 |
| C2bs | AUROC | 0.772 (0.720 to 0.825) | 0.547 (0.495 to 0.600) | -0.226 |
| C2bs | matched AUROC | 0.771 (0.715 to 0.824) | 0.541 (0.472 to 0.613) | -0.230 |
| C2bs | FAR at 5% target | 0.049 (0.041 to 0.056) | 0.046 (0.029 to 0.063) | -0.003 |
| C2bs | recall, all faults | 0.556 (0.461 to 0.650) | 0.060 (0.024 to 0.108) | -0.496 |
| C4s | AP | 0.875 (0.815 to 0.923) | 0.289 (0.231 to 0.355) | -0.585 |
| C4s | AUROC | 0.943 (0.915 to 0.967) | 0.775 (0.728 to 0.821) | -0.168 |
| C4s | matched AUROC | 0.941 (0.910 to 0.967) | 0.779 (0.719 to 0.837) | -0.162 |
| C4s | FAR at 5% target | 0.048 (0.037 to 0.060) | 0.000 (0.000 to 0.000) | -0.048 |
| C4s | recall, all faults | 0.833 (0.758 to 0.900) | 0.000 (0.000 to 0.000) | -0.833 |

**Recall at the 5% false-alarm threshold by fault type, C3 and C4:**

| model | fault type | faulty windows | old key | new key | change |
|---|---|---|---|---|---|
| C3 | restriction | 156 | 0.564 (0.407 to 0.710) | 0.564 (0.407 to 0.710) | +0.000 |
| C3 | pump | 72 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) | +0.000 |
| C3 | bias | 69 | 0.493 (0.256 to 0.760) | 0.493 (0.256 to 0.760) | +0.000 |
| C3 | drift | 50 | 0.700 (0.462 to 0.939) | 0.540 (0.267 to 0.826) | -0.160 |
| C3 | stuck | 33 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) | +0.000 |
| C3 | leak | 57 | 0.614 (0.368 to 0.881) | 0.614 (0.368 to 0.881) | +0.000 |
| C3 | misrouting | 15 | 0.067 (0.000 to 0.167) | 0.067 (0.000 to 0.167) | +0.000 |
| C3 | multi | 44 | 0.886 (0.694 to 1.000) | 0.886 (0.694 to 1.000) | +0.000 |
| C4 | restriction | 156 | 0.981 (0.941 to 1.000) | 0.000 (0.000 to 0.000) | -0.981 |
| C4 | pump | 72 | 1.000 (1.000 to 1.000) | 0.000 (0.000 to 0.000) | -1.000 |
| C4 | bias | 69 | 0.565 (0.313 to 0.846) | 0.000 (0.000 to 0.000) | -0.565 |
| C4 | drift | 50 | 0.680 (0.380 to 1.000) | 0.000 (0.000 to 0.000) | -0.680 |
| C4 | stuck | 33 | 1.000 (1.000 to 1.000) | 0.000 (0.000 to 0.000) | -1.000 |
| C4 | leak | 57 | 0.456 (0.217 to 0.712) | 0.000 (0.000 to 0.000) | -0.456 |
| C4 | misrouting | 15 | 1.000 (1.000 to 1.000) | 0.000 (0.000 to 0.000) | -1.000 |
| C4 | multi | 44 | 1.000 (1.000 to 1.000) | 0.000 (0.000 to 0.000) | -1.000 |

**Shuffle control (mean and 2.5% to 97.5% range under permuted labels):**

| model | metric | old key | new key |
|---|---|---|---|
| C3 | ap | 0.127 (0.116 to 0.138) | 0.127 (0.117 to 0.139) |
| C3 | auroc | 0.500 (0.472 to 0.531) | 0.500 (0.475 to 0.528) |
| C3 | matched | 0.498 (0.463 to 0.531) | 0.498 (0.466 to 0.534) |
| C4 | ap | 0.125 (0.116 to 0.133) | 0.126 (0.117 to 0.135) |
| C4 | auroc | 0.499 (0.473 to 0.522) | 0.501 (0.477 to 0.529) |
| C4 | matched | 0.499 (0.468 to 0.529) | 0.498 (0.470 to 0.524) |
| C4s | ap | 0.125 (0.116 to 0.134) | 0.126 (0.117 to 0.136) |
| C4s | auroc | 0.499 (0.474 to 0.522) | 0.501 (0.474 to 0.533) |
| C4s | matched | 0.500 (0.468 to 0.532) | 0.498 (0.470 to 0.528) |

**Placebo (positions 1 to 5, label = fault later in the episode), matched AUROC:**

| model | old key | new key | change |
|---|---|---|---|
| C1 | 0.475 (0.424 to 0.529) | 0.516 (0.463 to 0.567) | +0.042 |
| C2a | 0.472 (0.420 to 0.522) | 0.562 (0.507 to 0.615) | +0.090 |
| C2b | 0.468 (0.433 to 0.501) | 0.548 (0.492 to 0.605) | +0.081 |
| C3 | 0.512 (0.472 to 0.552) | 0.508 (0.467 to 0.546) | -0.004 |
| C4 | 0.468 (0.428 to 0.507) | 0.556 (0.504 to 0.605) | +0.089 |
| C1s | 0.486 (0.436 to 0.542) | 0.549 (0.498 to 0.603) | +0.063 |
| C2as | 0.466 (0.415 to 0.513) | 0.555 (0.501 to 0.608) | +0.090 |
| C2bs | 0.514 (0.479 to 0.549) | 0.554 (0.498 to 0.607) | +0.040 |
| C4s | 0.495 (0.452 to 0.534) | 0.559 (0.508 to 0.609) | +0.064 |

**Largest contributors to the score on faulty windows:**

| model | old key | new key |
|---|---|---|
| C1 | PT-202B 0.14, PT-202A 0.14, TT-001 0.14 | PT-202B 0.14, PT-202A 0.14, TT-001 0.11 |
| C2b | LT-101 0.22, LT-103 0.20, LT-102 0.14 | LT-103 0.27, LT-101 0.17, LT-102 0.15 |
| C3 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.19 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.21 |
| C4 | C3 0.40, C2b 0.30, C1 0.15 | C3 0.46, C2a 0.21, C1 0.17 |

Under the new key the fused score C4 sits at its floor of the calibrated p-value (the maximum score) for 14.8% of fault-free and 51.6% of faulty validation windows (C4s: 14.8% and 51.6%). The 95th percentile of fault-free scores is then the maximum, no score exceeds it, and the alarm rule gives no alarm at all; false-alarm rate and recall of C4 are zero by construction, not a measurement of the detector. AP and AUROC remain defined (with ties).

## 3. Phase B: enhancements under grouped cross-validation

### 3.1 Data and protocol

Grouped CV uses 9,832 eligible train windows from 1,603 episodes, 1,253 faulty (prevalence 0.1274), in 22 units (family, atmosphere, temperature) assigned to 5 folds of 2,900, 1,325, 2,311, 1,847, 1,449 windows. Each fold is fitted on the fault-free windows of the other units and scores every window of its units. The validation benchmark is fitted on all fault-free train windows. The alarm threshold is the 95th percentile of fault-free scores of the other parity fold (5% false-alarm target); intervals are 95% bootstrap over episodes (1,000 resamples, seed 20261108).

### 3.2 Systems (fused score C4 of each system)

**grouped CV (out of fold, train):**

| system | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| B0 | 0.305 (0.257 to 0.360) | 0.674 (0.639 to 0.711) | 0.678 (0.638 to 0.720) |
| E1 | 0.359 (0.308 to 0.419) | 0.713 (0.679 to 0.749) | 0.713 (0.676 to 0.753) |
| E1+E2 | 0.358 (0.306 to 0.418) | 0.713 (0.679 to 0.750) | 0.713 (0.675 to 0.752) |
| E1+E3 | 0.346 (0.295 to 0.405) | 0.682 (0.648 to 0.720) | 0.681 (0.643 to 0.721) |
| E1+E4 | 0.415 (0.357 to 0.475) | 0.730 (0.695 to 0.765) | 0.728 (0.690 to 0.765) |

**validation (held-out combinations):**

| system | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| B0 | 0.290 (0.231 to 0.355) | 0.775 (0.726 to 0.821) | 0.777 (0.711 to 0.836) |
| E1 | 0.397 (0.317 to 0.484) | 0.803 (0.760 to 0.845) | 0.801 (0.746 to 0.852) |
| E1+E2 | 0.396 (0.316 to 0.484) | 0.803 (0.760 to 0.845) | 0.801 (0.746 to 0.852) |
| E1+E3 | 0.393 (0.313 to 0.480) | 0.792 (0.748 to 0.835) | 0.788 (0.733 to 0.842) |
| E1+E4 | 0.677 (0.596 to 0.749) | 0.860 (0.817 to 0.897) | 0.845 (0.800 to 0.886) |

### 3.3 Stop rule: paired differences against the previous kept system

A system is kept only if the lower bounds of the OOF differences of AP and of matched-stage AUROC are both above zero. Validation differences are shown for information.

| system | against | OOF AP difference | OOF matched AUROC difference | decision | validation AP difference | validation matched AUROC difference |
|---|---|---|---|---|---|---|
| E1 | B0 | 0.055 (0.035 to 0.075) | 0.035 (0.017 to 0.055) | kept | 0.107 (0.067 to 0.150) | 0.025 (-0.009 to 0.059) |
| E1+E2 | E1 | -0.002 (-0.005 to 0.001) | -0.000 (-0.002 to 0.001) | dropped | -0.001 (-0.002 to 0.000) | -0.000 (-0.001 to 0.001) |
| E1+E3 | E1 | -0.013 (-0.018 to -0.009) | -0.032 (-0.048 to -0.018) | dropped | -0.004 (-0.007 to -0.002) | -0.013 (-0.023 to -0.004) |
| E1+E4 | E1 | 0.055 (0.041 to 0.070) | 0.015 (0.008 to 0.021) | kept | 0.281 (0.220 to 0.331) | 0.044 (0.010 to 0.081) |

### 3.4 Components and the condition-only reference

**B0, grouped CV (out of fold, train):**

| score | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| C1n | 0.124 (0.109 to 0.143) | 0.509 (0.474 to 0.544) | 0.490 (0.446 to 0.535) |
| C2a | 0.123 (0.106 to 0.144) | 0.479 (0.445 to 0.514) | 0.473 (0.429 to 0.515) |
| C2b | 0.132 (0.113 to 0.158) | 0.498 (0.461 to 0.533) | 0.489 (0.443 to 0.531) |
| C3 | 0.588 (0.534 to 0.640) | 0.778 (0.740 to 0.812) | 0.786 (0.751 to 0.820) |
| C4 | 0.305 (0.257 to 0.360) | 0.674 (0.639 to 0.711) | 0.678 (0.638 to 0.720) |
| prior | 0.128 (0.111 to 0.150) | 0.500 (0.462 to 0.538) | 0.503 (0.454 to 0.548) |

**B0, validation (held-out combinations):**

| score | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| C1n | 0.144 (0.115 to 0.178) | 0.519 (0.471 to 0.565) | 0.506 (0.444 to 0.566) |
| C2a | 0.148 (0.117 to 0.186) | 0.550 (0.497 to 0.601) | 0.543 (0.477 to 0.609) |
| C2b | 0.134 (0.106 to 0.171) | 0.529 (0.477 to 0.583) | 0.521 (0.451 to 0.596) |
| C3 | 0.730 (0.649 to 0.797) | 0.859 (0.810 to 0.902) | 0.852 (0.800 to 0.896) |
| C4 | 0.290 (0.231 to 0.355) | 0.775 (0.726 to 0.821) | 0.777 (0.711 to 0.836) |
| prior | 0.131 (0.105 to 0.163) | 0.525 (0.466 to 0.579) | 0.523 (0.445 to 0.594) |

**E1+E4, grouped CV (out of fold, train):**

| score | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| C1n | 0.131 (0.114 to 0.150) | 0.495 (0.466 to 0.526) | 0.481 (0.447 to 0.518) |
| C2a | 0.130 (0.111 to 0.150) | 0.494 (0.463 to 0.523) | 0.501 (0.460 to 0.538) |
| C2b | 0.141 (0.120 to 0.167) | 0.522 (0.490 to 0.554) | 0.528 (0.487 to 0.567) |
| C3 | 0.588 (0.534 to 0.640) | 0.778 (0.740 to 0.812) | 0.786 (0.751 to 0.820) |
| C4 | 0.415 (0.357 to 0.475) | 0.730 (0.695 to 0.765) | 0.728 (0.690 to 0.765) |
| prior | 0.128 (0.111 to 0.150) | 0.500 (0.462 to 0.538) | 0.503 (0.454 to 0.548) |

**E1+E4, validation (held-out combinations):**

| score | AP | AUROC | matched-stage AUROC |
|---|---|---|---|
| C1n | 0.158 (0.130 to 0.193) | 0.545 (0.508 to 0.582) | 0.506 (0.460 to 0.548) |
| C2a | 0.152 (0.120 to 0.192) | 0.548 (0.502 to 0.596) | 0.552 (0.495 to 0.612) |
| C2b | 0.141 (0.110 to 0.183) | 0.534 (0.484 to 0.585) | 0.528 (0.461 to 0.592) |
| C3 | 0.730 (0.649 to 0.797) | 0.859 (0.810 to 0.902) | 0.852 (0.800 to 0.896) |
| C4 | 0.677 (0.596 to 0.749) | 0.860 (0.817 to 0.897) | 0.845 (0.800 to 0.886) |
| prior | 0.131 (0.105 to 0.163) | 0.525 (0.466 to 0.579) | 0.523 (0.445 to 0.594) |

`prior` scores a window by the fault prevalence of its set-condition regime among the fit windows. It sits at chance level, so the set conditions alone carry no information about faults in these splits and a gain over it is not explained by the conditions.

### 3.5 Operating point at the 5% false-alarm target (fused score)

**grouped CV (out of fold, train):**

| system | false-alarm rate | false alarms per day | recall, all faults | delay quartiles (s) | episodes never alarmed | localisation top-1 | localisation top-3 |
|---|---|---|---|---|---|---|---|
| B0 | 0.041 (0.031 to 0.053) | 11.88 | 0.267 (0.213 to 0.324) | 1112 / 1262 / 1490 | 210/290 | 0.093 (0.037 to 0.151) | 0.304 (0.199 to 0.404) |
| E1 | 0.051 (0.040 to 0.064) | 14.8 | 0.286 (0.231 to 0.343) | 1114 / 1280 / 1492 | 201/290 | 0.118 (0.062 to 0.179) | 0.319 (0.231 to 0.408) |
| E1+E2 | 0.051 (0.040 to 0.064) | 14.8 | 0.286 (0.231 to 0.343) | 1114 / 1280 / 1492 | 201/290 | 0.118 (0.062 to 0.179) | 0.319 (0.231 to 0.408) |
| E1+E3 | 0.051 (0.040 to 0.064) | 14.8 | 0.286 (0.231 to 0.343) | 1114 / 1280 / 1492 | 201/290 | 0.115 (0.060 to 0.173) | 0.284 (0.203 to 0.373) |
| E1+E4 | 0.051 (0.040 to 0.064) | 14.77 | 0.313 (0.258 to 0.372) | 1114 / 1320 / 1703 | 188/290 | 0.118 (0.062 to 0.179) | 0.319 (0.231 to 0.408) |

**validation (held-out combinations):**

| system | false-alarm rate | false alarms per day | recall, all faults | delay quartiles (s) | episodes never alarmed | localisation top-1 | localisation top-3 |
|---|---|---|---|---|---|---|---|
| B0 | 0.000 (0.000 to 0.000) | 0.0 | 0.000 (0.000 to 0.000) | nan / nan / nan | 120/120 | 0.046 (0.000 to 0.126) | 0.105 (0.025 to 0.214) |
| E1 | 0.000 (0.000 to 0.000) | 0.0 | 0.000 (0.000 to 0.000) | nan / nan / nan | 120/120 | 0.072 (0.017 to 0.144) | 0.257 (0.137 to 0.372) |
| E1+E2 | 0.000 (0.000 to 0.000) | 0.0 | 0.000 (0.000 to 0.000) | nan / nan / nan | 120/120 | 0.072 (0.017 to 0.144) | 0.257 (0.137 to 0.372) |
| E1+E3 | 0.000 (0.000 to 0.000) | 0.0 | 0.000 (0.000 to 0.000) | nan / nan / nan | 120/120 | 0.066 (0.015 to 0.136) | 0.257 (0.137 to 0.372) |
| E1+E4 | 0.050 (0.043 to 0.058) | 14.47 | 0.558 (0.463 to 0.647) | 1085 / 1337 / 2169 | 39/120 | 0.072 (0.017 to 0.144) | 0.257 (0.137 to 0.372) |

False alarms per day are the false-alarm rate times 288 windows. Delay is the cutoff of the first alarmed faulty window minus the earliest onset, over episodes with at least one alarm; episodes never alarmed are counted separately and not imputed. Localisation covers single-component sensor faults (bias, drift, stuck) of single-fault episodes: the faulty tag is ranked among the 14 by the per-tag evidence of the system, and ties count against it. Chance is 7.1% for top-1 and 21.4% for top-3. Equipment faults are not scored because the reference declares no instrument-to-equipment mapping.

### 3.6 Recall by fault type at the 5% false-alarm target

**grouped CV (out of fold, train):**

| fault type | faulty windows | B0 fused | E1+E4 fused | C3 alone |
|---|---|---|---|---|
| restriction | 490 | 0.120 (0.070 to 0.184) | 0.155 (0.098 to 0.224) | 0.376 (0.290 to 0.467) |
| pump | 69 | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| bias | 132 | 0.151 (0.010 to 0.314) | 0.151 (0.010 to 0.314) | 0.204 (0.061 to 0.383) |
| drift | 197 | 0.431 (0.257 to 0.583) | 0.579 (0.412 to 0.739) | 0.904 (0.827 to 0.965) |
| stuck | 79 | 0.506 (0.210 to 0.774) | 0.506 (0.210 to 0.774) | 0.747 (0.567 to 0.908) |
| leak | 146 | 0.144 (0.025 to 0.283) | 0.192 (0.060 to 0.352) | 0.363 (0.215 to 0.541) |
| misrouting | 9 | 0.000 (0.000 to 0.000) | 0.000 (0.000 to 0.000) | 0.222 (0.167 to 0.333) |
| multi | 131 | 0.305 (0.156 to 0.449) | 0.344 (0.200 to 0.493) | 0.710 (0.571 to 0.833) |

**validation (held-out combinations):**

| fault type | faulty windows | B0 fused | E1+E4 fused | C3 alone |
|---|---|---|---|---|
| restriction | 156 | 0.000 (0.000 to 0.000) | 0.404 (0.259 to 0.555) | 0.564 (0.407 to 0.710) |
| pump | 72 | 0.000 (0.000 to 0.000) | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| bias | 69 | 0.000 (0.000 to 0.000) | 0.493 (0.256 to 0.760) | 0.493 (0.256 to 0.760) |
| drift | 50 | 0.000 (0.000 to 0.000) | 0.320 (0.023 to 0.652) | 0.540 (0.267 to 0.826) |
| stuck | 33 | 0.000 (0.000 to 0.000) | 1.000 (1.000 to 1.000) | 1.000 (1.000 to 1.000) |
| leak | 57 | 0.000 (0.000 to 0.000) | 0.456 (0.208 to 0.713) | 0.614 (0.368 to 0.881) |
| misrouting | 15 | 0.000 (0.000 to 0.000) | 0.067 (0.000 to 0.333) | 0.067 (0.000 to 0.167) |
| multi | 44 | 0.000 (0.000 to 0.000) | 0.727 (0.413 to 0.974) | 0.886 (0.694 to 1.000) |

### 3.7 Controls (fused score of every system)

**grouped CV (out of fold, train):**

| system | shuffle AP | shuffle AUROC | shuffle matched AUROC | placebo matched AUROC | constant columns |
|---|---|---|---|---|---|
| B0 | 0.128 | 0.500 | 0.500 | 0.459 (0.423 to 0.493) | none |
| E1 | 0.128 | 0.500 | 0.499 | 0.473 (0.442 to 0.504) | none |
| E1+E2 | 0.128 | 0.500 | 0.499 | 0.472 (0.441 to 0.504) | none |
| E1+E3 | 0.128 | 0.500 | 0.500 | 0.470 (0.440 to 0.501) | none |
| E1+E4 | 0.128 | 0.500 | 0.499 | 0.477 (0.447 to 0.507) | none |

**validation (held-out combinations):**

| system | shuffle AP | shuffle AUROC | shuffle matched AUROC | placebo matched AUROC | constant columns |
|---|---|---|---|---|---|
| B0 | 0.126 | 0.501 | 0.498 | 0.559 (0.507 to 0.606) | none |
| E1 | 0.126 | 0.501 | 0.499 | 0.552 (0.504 to 0.601) | none |
| E1+E2 | 0.126 | 0.501 | 0.499 | 0.552 (0.505 to 0.601) | none |
| E1+E3 | 0.126 | 0.501 | 0.499 | 0.546 (0.496 to 0.596) | none |
| E1+E4 | 0.126 | 0.501 | 0.499 | 0.523 (0.486 to 0.563) | none |

**Largest contributors on faulty windows, grouped CV (out of fold, train):**

| system | score | top contributors (share) |
|---|---|---|
| B0 | C3 | R1_mass_balance 0.34, R2_pump_head 0.21, R4_receipt_line 0.20, R3_discharge_loss 0.15 |
| B0 | C4 | C3 0.41, C1n 0.22, C2b 0.19, C2a 0.18 |
| E1 | C3 | R1_mass_balance 0.34, R2_pump_head 0.21, R4_receipt_line 0.20, R3_discharge_loss 0.15 |
| E1 | C4 | C3 0.43, C2b 0.24, C2a 0.18, C1n 0.15 |
| E1+E2 | C3 | R1_mass_balance 0.33, R2_pump_head 0.21, R4_receipt_line 0.20, R3_discharge_loss 0.15 |
| E1+E2 | C4 | C3 0.42, C2b 0.24, C2a 0.18, C1n 0.15 |
| E1+E3 | C3 | R5_temperature_pair 0.34, R1_mass_balance 0.25, R2_pump_head 0.18, R3_discharge_loss 0.12 |
| E1+E3 | C4 | C3 0.42, C2b 0.24, C2a 0.18, C1n 0.16 |
| E1+E4 | C3 | R1_mass_balance 0.34, R2_pump_head 0.21, R4_receipt_line 0.20, R3_discharge_loss 0.15 |
| E1+E4 | C4 | C3 0.49, C2b 0.20, C1n 0.17, C2a 0.14 |

**Largest contributors on faulty windows, validation (held-out combinations):**

| system | score | top contributors (share) |
|---|---|---|
| B0 | C3 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.21, R4_receipt_line 0.05 |
| B0 | C4 | C3 0.45, C2a 0.21, C1n 0.18, C2b 0.17 |
| E1 | C3 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.21, R4_receipt_line 0.05 |
| E1 | C4 | C3 0.47, C2b 0.25, C2a 0.16, C1n 0.12 |
| E1+E2 | C3 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.21, R4_receipt_line 0.05 |
| E1+E2 | C4 | C3 0.47, C2b 0.25, C2a 0.16, C1n 0.12 |
| E1+E3 | C3 | R2_pump_head 0.39, R3_discharge_loss 0.21, R5_temperature_pair 0.19, R1_mass_balance 0.17 |
| E1+E3 | C4 | C3 0.46, C2b 0.25, C2a 0.16, C1n 0.12 |
| E1+E4 | C3 | R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.21, R4_receipt_line 0.05 |
| E1+E4 | C4 | C3 0.58, C1n 0.20, C2b 0.13, C2a 0.09 |

Shuffle means sit at prevalence and 0.5. The placebo separates windows of positions 1 to 5 by whether the episode contains a fault later; a lower bound above 0.5 would mean the score reads the kind of episode. No column used by a component is constant across faulty windows. The set conditions that enter E1 take 2 (atmosphere), 4 (temperature) and 4 (set point) distinct values in train.

### 3.8 Candidates

**E1, set-point-conditioned baselines: kept.** In a fault-free plant the expected level of each column follows the set conditions, so a regression generalises to combinations with few fault-free windows. The gain is in the fused score; C1n, C2a and C2b stay near prevalence (section 3.4).

**E2, mass balance with flow terms: dropped.** The R1 of C3 already contains the storage term. Fitted tank areas on all fault-free train windows are 705.1, 705.5 and 705.6 without the added terms and 703.9, 703.3 and 703.7 with them: all positive, and almost the same. The added flow-meter term is -0.0071 per unit of FT-201 and the set-point term 0.0019 per m3/h. The differences from the previous system are zero within the interval.

**E3, related sensor pair residuals: dropped.** R6 (the two pump discharges when both pumps run) never applies: no train or validation window has both pumps running (windows per pump state in train: A only 3,958, B only 1,389, both 0, none 4,485; in validation: A only 2,245, B only 1,360, both 0, none 375). R5 (tank temperatures against their median) became the largest contributor to C3 (share 0.34 on faulty windows out of fold) and lowered AP and matched-stage AUROC. Recall of C3 at the 5% target for bias went from 0.204 to 0.182 and for drift from 0.904 to 0.838, so it did not help the faults it was meant for. The reason was not investigated within the time-box.

**E4, out-of-sample calibration: kept.** Reference scores come from inner grouped cross-fitting instead of the fit windows. Out of fold it adds to AP and to matched-stage AUROC. On validation it restores the alarm rule: the 95th percentile of fault-free scores is no longer the maximum score (section 3.5).

## 4. Reading of the results

- The stop rule was applied to systems (fusions). No fused system beats C3 alone out of fold: the paired difference of the final fusion minus C3 alone is -0.173 (-0.203 to -0.143) in AP and -0.058 (-0.083 to -0.032) in matched-stage AUROC out of fold, and -0.053 (-0.076 to -0.034) and -0.006 (-0.025 to 0.015) on validation. The components that carry no signal are fused by the minimum p-value; a plausible reason for the loss is that they raise scores of fault-free windows, which was not tested.
- C3, the topology residuals, carries almost all detectable signal: pump, stuck and drift faults are found, restriction and leak partly, misrouting and bias poorly. These are residuals fitted on a few tags; this is a result about this simulator and these windows, and tests of reduced models are not independent validation.
- Under the old key the validation results of C2b (AP 0.648) and C4 (AP 0.887) rested on baselines selected by the on/off tags. Fault effects in the key (restriction and misrouting) can contribute, and so can the commanded lineup, which an operator sets and which the key of Amendment 2 does not contain. This work does not separate the two; a key that adds the commanded mode would, and was not run because it is outside the registered candidates.
- Grouped CV leaves out whole units, but fault-free windows of the same atmosphere and temperature from other families stay in the fit set. Validation has fewer such windows, and its numbers are in places higher than CV: do not read the difference as a trend.
- The pump state used by R2 and R3 comes from the pump run tags, as before. Windows with no pump running (the state `none`) get no pump residual.
- Delay is bounded by the 300 s window grid. Many faulty episodes are never alarmed at the 5% target, so the delay quartiles describe only the episodes that are.
- The test split was not opened: the guard recorded no rejected attempt.

## 5. Deviations from the plan

- The audit hook was widened to the label file of train and validation episodes (plan section 11.2), the only source of the set conditions and fault onsets.
- B0 uses C1n, which has no CUSUM component, as registered in section 12.2. The Amendment 2 re-run keeps the CUSUM.
- The stop rule was applied to fused systems; section 4 gives the reading against C3.
- E3 and E4 were applied to the system kept after E1, because E2 was dropped.
- The five systems were run twice: the second run added the recorded R1 terms and pump-state counts; scores and metrics were identical.
- C1 and C2 rows were added to the old-key comparison because they feed C4.

## 6. Reproduction

Seed 20261108 everywhere. WORK is a scratch folder.

```
.venv/bin/python tools/detector/run.py score --release data/reference_release_v2/verum_reference_v2 --work WORK/v2/work_lineup --key lineup
.venv/bin/python tools/detector/run.py score --release data/reference_release_v2/verum_reference_v2 --work WORK/v2/work_conditions --key conditions
.venv/bin/python tools/detector/run.py evaluate --work WORK/v2/work_conditions --out WORK/v2/results_conditions.json
.venv/bin/python tools/detector/run.py cv --release data/reference_release_v2/verum_reference_v2 --work WORK/cv/B0 --spec ''
.venv/bin/python tools/detector/run.py cv --release data/reference_release_v2/verum_reference_v2 --work WORK/cv/E1 --spec E1
.venv/bin/python tools/detector/run.py cv --release data/reference_release_v2/verum_reference_v2 --work WORK/cv/E1_E2 --spec E1,E2
.venv/bin/python tools/detector/run.py cv --release data/reference_release_v2/verum_reference_v2 --work WORK/cv/E1_E3 --spec E1,E3
.venv/bin/python tools/detector/run.py cv --release data/reference_release_v2/verum_reference_v2 --work WORK/cv/E1_E4 --spec E1,E4
.venv/bin/python tools/detector/run.py cveval --work WORK/cv/<system> --out WORK/cv/<system>/results.json
.venv/bin/python tools/detector/run.py cvreport --work WORK --out reports/detector_v2_results.md
```
