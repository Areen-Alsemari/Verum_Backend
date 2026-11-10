# Detector experiment: results

All data are simulated from one synthetic terminal. Nothing here is a statement about a real plant.

| Item | Value |
|---|---|
| Plan | `a29af6d`, with Amendment 1 committed together with the harness |
| Harness | `41e4ba4`; diagnostics and report modules come with this report |
| Validation | 3980 windows with a valid label, 496 faulty, prevalence 0.1246 |
| Fit set | 8579 fault-free train windows |
| Seed | 20261108 for the random score, the bootstrap, the shuffles |
| Test split | not opened. The audit hook allowed these opens in the main process (examples: 2416, role_views: 4, role_views_manifest.json: 2), and 2276 raw-observation files of train and validation episodes in the workers. Rejected attempts: 0 in the main process, 0 in the workers |
| Raw rows against summaries | the mean of the raw 300 s rows equals the window summary mean (largest absolute difference 0.0) |
| Missing values | 0.0000 of the validation columns |
| Run time | scoring stage 114 s |

## 1. Summary

Prevalence of faulty windows in validation: 0.1246 (496 of 3980).

**Stop rule (registered candidates only): the experiment did not stop. Passing both conditions: C2a, C2b, C3, C4.** C1 did not. The current forest C0 has AP 0.149 [0.117, 0.181], whose interval contains the prevalence, and matched-stage AUROC 0.485 [0.435, 0.536], which contains 0.5: on these windows it is not distinguishable from chance.

The topology-residual detector C3 reaches AP 0.739 [0.661, 0.806] and matched-stage AUROC 0.852 [0.801, 0.899]; the fixed fusion C4 reaches AP 0.887 [0.835, 0.932] and matched-stage AUROC 0.940 [0.906, 0.968], at a false-alarm rate of about 5% by construction. The placebo control (post hoc) is near 0.5 for every model, and the result holds on windows whose operating regime was seen in fault-free training. Details, limits and what is not supported are below.

## 2. Registered candidates and baselines (validation)

| Model | AP | AUROC | Matched-stage AUROC | False-alarm rate | Recall |
|---|---|---|---|---|---|
| always flag | 0.125 [0.102, 0.145] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 1.000 (flags every window) | 1.000 (flags every window) |
| random score | 0.129 [0.105, 0.156] | 0.503 [0.474, 0.533] | 0.505 [0.467, 0.542] | 0.051 [0.043, 0.058] | 0.057 [0.037, 0.077] |
| C0 current Agent 2 forest | 0.149 [0.117, 0.181] | 0.558 [0.519, 0.596] | 0.485 [0.435, 0.536] | 0.051 [0.042, 0.059] | 0.062 [0.033, 0.096] |
| C1 per-tag + CUSUM | 0.155 [0.122, 0.188] | 0.536 [0.489, 0.582] | 0.549 [0.479, 0.614] | 0.048 [0.035, 0.062] | 0.050 [0.026, 0.078] |
| C2a PCA, all tags | 0.427 [0.339, 0.509] | 0.723 [0.674, 0.774] | 0.698 [0.640, 0.750] | 0.046 [0.039, 0.054] | 0.359 [0.275, 0.446] |
| C2b PCA, process groups | 0.648 [0.559, 0.726] | 0.771 [0.715, 0.825] | 0.777 [0.719, 0.831] | 0.053 [0.045, 0.062] | 0.556 [0.463, 0.644] |
| C3 topology residuals | 0.739 [0.661, 0.806] | 0.860 [0.811, 0.904] | 0.852 [0.801, 0.899] | 0.051 [0.044, 0.058] | 0.679 [0.592, 0.758] |
| C4 fusion | 0.887 [0.835, 0.932] | 0.943 [0.908, 0.970] | 0.940 [0.906, 0.968] | 0.049 [0.041, 0.058] | 0.839 [0.765, 0.905] |

False-alarm rate and recall use the cross-fitted 5% target. Intervals are 95% bootstrap intervals over whole episodes (1,000 resamples).

At its shipped threshold (0.0606) C0 alarms on 0.886 of fault-free windows and on 0.990 of faulty ones.

## 3. Recall by fault type at the 5% false-alarm target

| Model | restriction (n=156) | pump (n=72) | bias (n=69) | drift (n=50) | stuck (n=33) | leak (n=57) | misrouting (n=15) | multi (n=44) |
|---|---|---|---|---|---|---|---|---|
| C0 current Agent 2 forest | 0.03 [0.01, 0.07] | 0.06 [0.00, 0.11] | 0.06 [0.00, 0.15] | 0.06 [0.00, 0.12] | 0.12 [0.00, 0.46] | 0.05 [0.00, 0.10] | 0.20 [0.00, 0.50] | 0.11 [0.00, 0.32] |
| C1 per-tag + CUSUM | 0.07 [0.04, 0.11] | 0.01 [0.00, 0.05] | 0.09 [0.00, 0.24] | 0.00 [0.00, 0.00] | 0.03 [0.00, 0.10] | 0.05 [0.00, 0.16] | 0.00 [0.00, 0.00] | 0.07 [0.00, 0.18] |
| C2a PCA, all tags | 0.69 [0.55, 0.83] | 0.06 [0.01, 0.11] | 0.13 [0.02, 0.29] | 0.40 [0.11, 0.75] | 0.12 [0.00, 0.25] | 0.07 [0.01, 0.15] | 0.20 [0.17, 0.33] | 0.61 [0.30, 0.88] |
| C2b PCA, process groups | 0.98 [0.94, 1.00] | 0.06 [0.00, 0.10] | 0.13 [0.02, 0.29] | 0.70 [0.42, 1.00] | 0.45 [0.06, 0.88] | 0.09 [0.02, 0.17] | 1.00 [1.00, 1.00] | 0.91 [0.72, 1.00] |
| C3 topology residuals | 0.56 [0.41, 0.71] | 1.00 [1.00, 1.00] | 0.49 [0.26, 0.76] | 0.70 [0.46, 0.94] | 1.00 [1.00, 1.00] | 0.61 [0.37, 0.88] | 0.07 [0.00, 0.17] | 0.89 [0.69, 1.00] |
| C4 fusion | 0.98 [0.94, 1.00] | 1.00 [1.00, 1.00] | 0.57 [0.31, 0.85] | 0.68 [0.38, 1.00] | 1.00 [1.00, 1.00] | 0.46 [0.22, 0.71] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |

## 4. Sensitivity: temperature level removed (exploratory, outside the stop rule)

| Model | AP | AUROC | Matched-stage AUROC | False-alarm rate | Recall |
|---|---|---|---|---|---|
| C1s (temperature level removed) | 0.179 [0.143, 0.216] | 0.624 [0.584, 0.668] | 0.628 [0.571, 0.692] | 0.047 [0.034, 0.061] | 0.046 [0.023, 0.074] |
| C2as (temperature level removed) | 0.591 [0.506, 0.674] | 0.773 [0.720, 0.823] | 0.754 [0.698, 0.808] | 0.046 [0.039, 0.054] | 0.500 [0.412, 0.598] |
| C2bs (temperature level removed) | 0.645 [0.558, 0.725] | 0.772 [0.720, 0.825] | 0.771 [0.715, 0.824] | 0.049 [0.041, 0.056] | 0.556 [0.461, 0.650] |
| C4s (temperature level removed) | 0.875 [0.815, 0.923] | 0.943 [0.915, 0.967] | 0.941 [0.910, 0.967] | 0.048 [0.037, 0.060] | 0.833 [0.758, 0.900] |

C3 does not use temperature and is not repeated. The sensitivity was declared in Amendment 1 because train and validation hold different temperature set points.

## 5. Pre-registered controls

Shuffle test (200 permutations, mean and 2.5% to 97.5% range):

| Model | AP | AUROC | Matched-stage AUROC |
|---|---|---|---|
| always flag | 0.125 [0.125, 0.125] | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] |
| random score | 0.127 [0.115, 0.139] | 0.499 [0.473, 0.529] | 0.499 [0.469, 0.531] |
| C0 current Agent 2 forest | 0.127 [0.118, 0.138] | 0.502 [0.474, 0.526] | 0.500 [0.471, 0.533] |
| C1 per-tag + CUSUM | 0.126 [0.116, 0.136] | 0.500 [0.473, 0.526] | 0.499 [0.468, 0.529] |
| C2a PCA, all tags | 0.126 [0.117, 0.138] | 0.499 [0.476, 0.523] | 0.500 [0.468, 0.535] |
| C2b PCA, process groups | 0.126 [0.116, 0.139] | 0.497 [0.473, 0.522] | 0.500 [0.466, 0.533] |
| C3 topology residuals | 0.127 [0.116, 0.138] | 0.500 [0.472, 0.531] | 0.498 [0.463, 0.531] |
| C4 fusion | 0.125 [0.116, 0.133] | 0.499 [0.473, 0.522] | 0.499 [0.468, 0.529] |
| C1s (temperature level removed) | 0.126 [0.116, 0.137] | 0.500 [0.471, 0.528] | 0.501 [0.469, 0.532] |
| C2as (temperature level removed) | 0.126 [0.116, 0.137] | 0.498 [0.472, 0.523] | 0.500 [0.465, 0.534] |
| C2bs (temperature level removed) | 0.126 [0.117, 0.139] | 0.498 [0.472, 0.525] | 0.499 [0.466, 0.535] |
| C4s (temperature level removed) | 0.125 [0.116, 0.134] | 0.499 [0.474, 0.522] | 0.500 [0.468, 0.532] |

Matched-position control: the matched-stage AUROC column of the tables above, for every candidate and for C0.

Columns taking fewer than 3 distinct values or having zero variance across faulty windows: none.

Mean share of the total contribution on faulty windows, top 10:

- C1 per-tag + CUSUM: PT-202B 0.14, PT-202A 0.14, TT-001 0.14, TT-102 0.13, TT-101 0.13, TT-103 0.13, FT-201 0.07, PT-203 0.03, LT-103 0.03, PT-201 0.02
- C2a PCA, all tags: LT-103 0.15, LT-101 0.13, PT-202B 0.10, LT-102 0.09, TT-101 0.08, TT-001 0.08, TT-103 0.08, TT-102 0.08, PT-202A 0.07, PT-201 0.04
- C2b PCA, process groups: LT-101 0.22, LT-103 0.20, LT-102 0.14, TT-101 0.09, TT-102 0.09, TT-001 0.08, TT-103 0.08, FT-001 0.02, PT-202B 0.02, PT-202A 0.02
- C3 topology residuals: R2_pump_head 0.44, R3_discharge_loss 0.26, R1_mass_balance 0.19, R4_receipt_line 0.06
- C4 fusion: C3 0.40, C2b 0.30, C1 0.15, C2a 0.15
- C1s (temperature level removed): PT-202B 0.29, PT-202A 0.28, FT-201 0.15, PT-203 0.06, LT-103 0.05, PT-201 0.04, LT-101 0.03, LT-102 0.03, PT-001 0.01, FT-001 0.01
- C2as (temperature level removed): LT-101 0.19, LT-103 0.18, LT-102 0.12, PT-202B 0.09, PT-202A 0.08, PT-201 0.06, FT-201 0.04, PT-203 0.04, TT-101 0.04, PT-001 0.03
- C2bs (temperature level removed): LT-101 0.27, LT-103 0.24, LT-102 0.16, TT-101 0.05, TT-102 0.05, TT-001 0.05, TT-103 0.04, FT-001 0.04, PT-001 0.03, PT-202A 0.02
- C4s (temperature level removed): C3 0.39, C2b 0.27, C2a 0.20, C1 0.14

For C1 and C2 the temperature tags are among the largest contributors: those scores are partly driven by the held-out set point. For C3 the contributors are physical residuals (pump head, discharge loss, mass balance).

## 6. Post-hoc controls (added after seeing the results)

The first results were stronger than expected, so three controls were added. They take no part in the stop rule.

**Regime coverage.** 200 of the faulty validation windows lie in an operating regime with fewer than 200 fault-free train windows, against 0 fault-free windows. Almost all restriction and misrouting windows are among them (restriction in seen regimes: 1 of 156; misrouting: 0 of 15). A detector that reacts to an unusual regime would look good on exactly these windows, and this data cannot tell it from a physical detection, because no fault-free validation window is in such a regime. So the restriction and misrouting recalls in section 3 are not interpretable.

**Placebo.** Windows at positions 1 to 5, before any fault can occur, are labelled by whether their episode contains a fault later. A score that reads the kind of episode would separate them.

| Model | AP (seen regimes) | Matched-stage AUROC (seen regimes) | Placebo AUROC |
|---|---|---|---|
| C0 current Agent 2 forest | 0.104 [0.070, 0.141] | 0.490 [0.429, 0.551] | 0.498 [0.465, 0.533] |
| C1 per-tag + CUSUM | 0.091 [0.066, 0.126] | 0.571 [0.487, 0.651] | 0.475 [0.424, 0.529] |
| C2a PCA, all tags | 0.192 [0.110, 0.277] | 0.554 [0.486, 0.619] | 0.472 [0.420, 0.522] |
| C2b PCA, process groups | 0.319 [0.204, 0.430] | 0.629 [0.560, 0.698] | 0.468 [0.433, 0.501] |
| C3 topology residuals | 0.769 [0.677, 0.857] | 0.871 [0.803, 0.935] | 0.512 [0.472, 0.552] |
| C4 fusion | 0.782 [0.690, 0.865] | 0.905 [0.852, 0.952] | 0.468 [0.428, 0.507] |

**Recall by type among windows in seen regimes** (alarmed / total, same 5% target):

| Model | restriction | pump | bias | drift | stuck | leak | misrouting | multi |
|---|---|---|---|---|---|---|---|---|
| C3 topology residuals | 0/1 | 72/72 | 34/69 | 35/50 | 33/33 | 35/57 | - | 14/14 |
| C4 fusion | 0/1 | 72/72 | 39/69 | 34/50 | 33/33 | 26/57 | - | 14/14 |
| C2b PCA, process groups | 0/1 | 4/72 | 9/69 | 35/50 | 15/33 | 5/57 | - | 11/14 |

**Matched-stage AUROC within each temperature class:**

| Model | 35.0 C (n=1615, faulty=208) | 40.0 C (n=2176, faulty=270) | 45.0 C (n=189, faulty=18) |
|---|---|---|---|
| C0 current Agent 2 forest | 0.457 | 0.489 | 0.667 |
| C2b PCA, process groups | 0.789 | 0.780 | 0.715 |
| C3 topology residuals | 0.811 | 0.908 | 0.569 |
| C4 fusion | 0.932 | 0.969 | 0.729 |

## 7. What is supported and what is not

Supported, for this simulated terminal and these validation windows:

- Fault-free-trained physics residuals (C3) and their fixed fusion with PCA and per-tag scores (C4) separate faulty from fault-free windows far better than the current forest and the trivial baselines, also at matched episode stage (0.852 [0.801, 0.899] and 0.940 [0.906, 0.968]).
- The advantage survives restricting to windows in regimes seen in fault-free training: C3 AP 0.769 [0.677, 0.857], matched 0.871 [0.803, 0.935]; C4 AP 0.782 [0.690, 0.865], matched 0.905 [0.852, 0.952].
- The placebo AUROC of every model is near 0.5: the scores do not read the kind of episode before a fault begins.
- At 5% false alarms, among windows in seen regimes (C3, C4): pump C3 72/72 (100%), C4 72/72 (100%); stuck C3 33/33 (100%), C4 33/33 (100%); drift C3 35/50 (70%), C4 34/50 (68%); bias C3 34/69 (49%), C4 39/69 (57%); leak C3 35/57 (61%), C4 26/57 (46%).

Not supported:

- That the current forest has any skill here: its AP interval contains the prevalence and its matched-stage AUROC interval contains 0.5.
- That per-tag baselines with CUSUM (C1) or PCA on all tags (C2a) work: C1 fails the stop rule, C2a and C2b are driven by tank levels and temperatures and are weak on seen regimes.
- Anything about restriction and misrouting faults (section 6), and about 45 degrees C (only 18 faulty windows; matched AUROC much lower).
- Any claim on real plants, other terminals, or the test split, which stays untouched for one confirming run. Window-level detection is not localisation: nothing here names the faulty asset.
- Thresholds are cross-fitted on validation fault-free windows; the intervals do not include that uncertainty, nor the in-sample calibration of the C4 p-values. The tag-to-location mapping used by C3 follows the tag names and is an assumption.

## 8. Deviations from the plan

- Amendment 1 (temperature set points differ between train and validation) added the four sensitivity variants; it was committed before any label-based metric was computed.
- Section 6 was added after the results were seen, for the reason given there.
- The plan said C1 runs on raw series; the raw rows come from the same window as the summary and the CUSUM therefore uses more input than the Agent 2 request carries.
- Ties in C4 (p-values cannot fall below 1/(n+1)) make part of its score range flat; ties are handled by average ranks.

## 9. Reproduction

```bash
git switch detector-experiment
.venv/bin/python tools/detector/run.py score --release data/reference_release_v2/verum_reference_v2 --work WORK
.venv/bin/python tools/detector/run.py evaluate --work WORK --out WORK/results.json
.venv/bin/python tools/detector/run.py diagnose --release data/reference_release_v2/verum_reference_v2 --work WORK --out WORK/diagnostics.json
.venv/bin/python tools/detector/run.py report --work WORK --results WORK/results.json --diagnostics WORK/diagnostics.json --out reports/detector_experiment_results.md
.venv/bin/pytest tests/regression/test_detector_experiment.py -q
```

Seed 20261108 for every random draw. The scoring stage takes about two minutes, the evaluation about 20 seconds.
