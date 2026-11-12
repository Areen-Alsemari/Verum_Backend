# Agent 5: the Agent 2 odds update does not pass the stop rule and is removed

Results of the evaluation pre-registered in `reports/agent5_evidence_ranking_design.md` (section 5). The odds update of Agent 5 scores from the Agent 2 window assessment was implemented, tested and evaluated as registered. It does not pass the stop rule, so it is removed and the ranking of Agent 5 is unchanged. Hypothesis ids, components and scores of the shipped Agent 5 are as before.

## 1. Outcome

- The lower bound of the paired bootstrap difference in top-1 accuracy is below zero on the full validation split, for the family measure (-0.021) and for the mechanism and asset measure (-0.004). The point differences are -0.006 and +0.004.
- Fault-free windows: hypotheses at or above 0.9 fall from 28 to 16, at or above 0.5 from 143 to 137, and at their own threshold from 301 to 295. That condition is met; the accuracy condition is not.
- The shuffle control (assessments taken from other windows) gives a mean change of -0.010 in family top-1 and -0.006 in exact top-1, so no gain is found for the shuffle to remove; the update is not better than noise.
- The code that was run is the state of commit `e026e23` of the branch `agent5-evidence-ranking`. The removal is a later commit; check out `e026e23` to rerun it.

## 2. What was run

- Estimation: 9,832 train windows (8,579 fault-free), residual states from out-of-fold models and the pinned thresholds, the family of each single-fault window from `mechanism.py`. Smoothing add-one, floor 0.05, cap 20, no ratio for a family with fewer than 10 windows. The audit hook recorded no rejected open; only train files were opened. A second run gave the same bytes.
- Evaluation: the full validation split, 3,980 windows with a valid label (496 faulty, 3,484 fault-free), through the runner with the installed agents for roles 1 to 4 and 7. The roles after the diagnosis were placeholders, because only the Agent 5 request was needed; that request, with the real Agent 2 report inside it, was stored for each window, and each Agent 5 variant was run on the stored requests with the classifier run once per window. The 169 validation windows of the earlier 181-window sample were scored from the same results. The audit hook recorded no rejected open; the test split was not opened.
- Likelihood ratios (train), as exceeded / within normal:

| family | residual | train windows | exceeded | within normal | combination |
|---|---|---|---|---|---|
| pump head loss | R2 | 69 | 19.67 | 0.05 | single |
| restriction at a pump inlet valve | R2 | 48 | 16.76 | 0.17 | single |
| restriction at a pump outlet valve | R3 | 79 | 19.22 | 0.05 | single |
| restriction at a receipt-side valve | R4 | 302 | 8.07 | 0.63 | single |
| leak between the two meters | R1 | 116 | 13.53 | 0.34 | single |
| flow-meter sensor fault | R1 | 106 | 15.52 | 0.23 | single |
| level-sensor drift or stuck | R1 | 167 | 19.84 | 0.05 | single |
| suction-header pressure transmitter fault | R2 | 29 | 4.51 | 0.82 | single |
| discharge-header pressure transmitter fault | R3 | 16 | 8.87 | 0.58 | single |
| receipt-line pressure transmitter fault | R4 | 9 | 1.00 | 1.00 | single |
| pump A discharge transmitter fault | R2, R3 | 20 | 12.70 | 0.38 | largest (phi 1.00) |
| pump B discharge transmitter fault | R2, R3 | 21 | 6.07 | 0.73 | largest (phi 1.00) |

## 3. Full validation split

Accuracy on faulty windows, previous Agent 5 against the update, with the paired difference and its 95% interval over whole episodes (1,000 resamples):

| measure | windows | previous | update | paired difference |
|---|---|---|---|---|
| family top-1 | 496 | 0.609 | 0.603 | -0.006 (-0.021 to +0.006) |
| family top-3 | 496 | 0.625 | 0.625 | +0.000 (+0.000 to +0.000) |
| exact top-1 | 496 | 0.431 | 0.435 | +0.004 (-0.004 to +0.012) |
| exact top-3 | 496 | 0.442 | 0.442 | +0.000 (+0.000 to +0.000) |

Top-1 by the family of the injected fault:

| injected family | windows | family before | exact before | family after | exact after |
|---|---|---|---|---|---|
| leak | 57 | 0.070 | 0.000 | 0.070 | 0.000 |
| misrouting | 15 | 0.667 | 0.667 | 0.667 | 0.667 |
| pump | 72 | 0.750 | 0.694 | 0.792 | 0.736 |
| restriction | 156 | 0.929 | 0.821 | 0.891 | 0.814 |
| sensor fault | 152 | 0.355 | 0.007 | 0.355 | 0.007 |
| several components | 44 | 0.795 | 0.568 | 0.795 | 0.568 |

Fault-free windows:

| variant | windows | hypotheses | mean score | at own threshold | at 0.5 | at 0.9 |
|---|---|---|---|---|---|---|
| prev | 3484 | 301 | 0.525 | 301 | 143 | 28 |
| new | 3484 | 301 | 0.511 | 295 | 137 | 16 |

Ranking changes (windows with a hypothesis; first hypothesis changes; order changes; faulty windows; top-1 gained; top-1 lost, by mechanism and asset):

| windows with a hypothesis | first hypothesis changes | order changes | faulty windows | top-1 gained | top-1 lost |
|---|---|---|---|---|---|
| 633 | 9 | 11 | 355 | 3 | 1 |

Reliability of the score, by bin of 0.1, against the share of hypotheses that match an injected mechanism and asset. The weighted gap to the centre of the bin is 0.379 before and 0.378 after, so the score stays far from calibrated. Previous:

| score bin | hypotheses | match rate |
|---|---|---|
| 0.2 to 0.3 | 133 | 0.030 |
| 0.3 to 0.4 | 101 | 0.079 |
| 0.4 to 0.5 | 49 | 0.000 |
| 0.5 to 0.6 | 61 | 0.016 |
| 0.6 to 0.7 | 41 | 0.049 |
| 0.7 to 0.8 | 67 | 0.000 |
| 0.8 to 0.9 | 58 | 0.190 |
| 0.9 to 1.0 | 289 | 0.678 |

With the update:

| score bin | hypotheses | match rate |
|---|---|---|
| 0.2 to 0.3 | 133 | 0.030 |
| 0.3 to 0.4 | 101 | 0.079 |
| 0.4 to 0.5 | 49 | 0.000 |
| 0.5 to 0.6 | 61 | 0.016 |
| 0.6 to 0.7 | 41 | 0.049 |
| 0.7 to 0.8 | 67 | 0.000 |
| 0.8 to 0.9 | 58 | 0.190 |
| 0.9 to 1.0 | 289 | 0.678 |

### Reliability of the score, new (weighted gap 0.378)
| score bin | hypotheses | match rate |
|---|---|---|
| 0.1 to 0.2 | 12 | 0.000 |
| 0.2 to 0.3 | 134 | 0.022 |
| 0.3 to 0.4 | 89 | 0.011 |
| 0.4 to 0.5 | 47 | 0.000 |
| 0.5 to 0.6 | 56 | 0.018 |
| 0.6 to 0.7 | 37 | 0.027 |
| 0.7 to 0.8 | 69 | 0.014 |
| 0.8 to 0.9 | 75 | 0.253 |
| 0.9 to 1.0 | 280 | 0.700 |

Controls:

| control | result |
|---|---|
| ablation: output identical to the previous Agent 5 | 3980 of 3980 |
| shuffle 0: change in family top-1, family top-3, exact top-1, exact top-3 | -0.010, +0.000, -0.006, +0.000 |
| shuffle 1: change in family top-1, family top-3, exact top-1, exact top-3 | -0.014, +0.000, -0.010, +0.000 |
| shuffle 2: change in family top-1, family top-3, exact top-1, exact top-3 | -0.010, +0.000, -0.006, +0.000 |
| shuffle 3: change in family top-1, family top-3, exact top-1, exact top-3 | -0.006, +0.000, -0.004, +0.000 |
| shuffle 4: change in family top-1, family top-3, exact top-1, exact top-3 | -0.008, +0.000, -0.006, +0.000 |
| shuffle: mean change | -0.010, +0.000, -0.006, +0.000 |

Stop rule:

- lower bound of the paired difference, family top-1: -0.021; mechanism and asset top-1: -0.004; above zero for either: False
- fault-free hypotheses at their own threshold, at 0.5, at 0.9: before 301, 143, 28; after 295, 137, 16; no increase: True
- outcome: do not keep; report the negative result

## 4. The 169 validation windows of the earlier sample

| measure | windows | previous | update | paired difference |
|---|---|---|---|---|
| family top-1 | 87 | 0.506 | 0.517 | +0.011 (+0.000 to +0.035) |
| family top-3 | 87 | 0.517 | 0.517 | +0.000 (+0.000 to +0.000) |
| exact top-1 | 87 | 0.310 | 0.322 | +0.011 (+0.000 to +0.035) |
| exact top-3 | 87 | 0.322 | 0.322 | +0.000 (+0.000 to +0.000) |

| variant | windows | hypotheses | mean score | at own threshold | at 0.5 | at 0.9 |
|---|---|---|---|---|---|---|
| prev | 82 | 9 | 0.488 | 9 | 3 | 1 |
| new | 82 | 9 | 0.487 | 9 | 3 | 1 |

| control | result |
|---|---|
| ablation: output identical to the previous Agent 5 | 169 of 169 |
| shuffle 0: change in family top-1, family top-3, exact top-1, exact top-3 | +0.000, +0.000, +0.000, +0.000 |
| shuffle 1: change in family top-1, family top-3, exact top-1, exact top-3 | +0.000, +0.000, +0.000, +0.000 |
| shuffle 2: change in family top-1, family top-3, exact top-1, exact top-3 | +0.000, +0.000, +0.000, +0.000 |
| shuffle 3: change in family top-1, family top-3, exact top-1, exact top-3 | +0.011, +0.000, +0.011, +0.000 |
| shuffle 4: change in family top-1, family top-3, exact top-1, exact top-3 | +0.011, +0.000, +0.011, +0.000 |
| shuffle: mean change | +0.005, +0.000, +0.005, +0.000 |

The gain of +0.011 is one window of 87, as large as two of the five shuffles, and its lower bound is 0.000.

## 5. Why the update cannot help much here

- The set of hypotheses is fixed by the classifier. Of the 496 faulty windows, 141 have no hypothesis, 228 have one, 113 have two and 14 have three or more. A re-ranking can change the first hypothesis only in the last 127 windows. It changed it in 9 windows of the whole split.
- In those 9 windows, 3 pump fault windows gained a correct first hypothesis (a pump hypothesis for pump B moved above a bias hypothesis) and 6 restriction windows at the valve XV-PBO lost one. In all 6, a bias hypothesis on the transmitter PT-202A moved above the correct restriction. A restriction at a pump outlet valve and a fault of a discharge transmitter both raise R3, and the ratio for a fault of the transmitter PT-202A does not depend on whether pump A is the pump that runs. The ratios were not tuned after this was seen.
- Of the 799 hypotheses on the split, 514 kept their score, 202 rose and 83 fell. A fall in the count of fault-free hypotheses at or above 0.9 (28 to 16) can only come from the reductions.

## 6. Deviations and limits

- Pre-registration was followed. Four points that were not fixed in it: the reliability gap is computed against the centre of each bin; the ablation control compares the update with the previous Agent 5 on a request whose assessment is removed (the citations of the mechanism rule also depend on the assessment); the shuffle control permutes over the whole split; the estimation script had one lint-only edit after the first run, and the file it wrote was byte-identical before and after.
- The first scoring trial on 40 windows showed that the ablation had to be defined that way; no ratio, threshold or rule was changed after it.
- Agent 2 evidence is not independent of the observation vector that the classifier already reads, and the ratios were estimated against the fault-free windows, not against the classifier. A negative result here does not say that Agent 2 evidence has no value for diagnosis; it says that an odds update of the existing scores, with these ratios and this set of hypotheses, does not improve the first hypothesis on validation windows.
- The pressure-transmitter families of `mechanism.py` (their own commit) stay: they change citations and not scores.
