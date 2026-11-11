# Split audit

Read-only audit of how the train, validation and test splits are defined and what depends on them. Written from the committed code and documents and from metadata only. The test split was not opened as signal data or labels (see section 8).

Shorthand used below. A **unit** is the triple (scenario family, atmosphere, temperature set point), the unit the split rule works on. A **mode** is the lineup name of the campaign (for example `DELIVER_101_A`). A **window** is one 300 s snapshot of an episode (12 per episode); an **eligible** window has a valid diagnosis label (the supervised mask is true). A **lineup state** is the combination of the 16 on/off tags of a window (pumps, valves, level switches), the key used by the detector experiment.

## Answers in short

1. The split is by **episode**, and by unit before that. It is defined in `src/verum/campaign/splits.py` (`build_split_plan`, `split_of`), drawn from the campaign seed 20261101 and stored per episode in `data/campaign/evaluator/manifest.json`. The rule is documented in D86 and D155 of `docs/design_decisions.md`. The set-point mismatch between train and validation is **intended by that rule**: whole units are assigned to one split, 11 units go to validation and none of them has a train episode.
2. Section 3 gives the regimes by split. In eligible fault-free windows the temperature mixture differs a lot: train is 54% at 25 C and validation has none; validation is 55% at 40 C against 12% in train.
3. 23 of the 38 units have fewer than 200 fault-free train windows: all 13 non-train units, and 10 train units (three `branched` units with no eligible window, and seven small units: six at 45 C and `switch|inland|35`; section 4). At the level of the 16 on/off tags it is the reverse: 26 of the 38 lineup states seen in eligible windows have **no fault-free window at all in train or validation**; they hold the valve-restriction, misrouting and part of the multi-fault windows (section 4).
4. No episode, window, seed or file digest is shared between splits (section 5). For the test split this rests on the manifests and directory names only; window-level overlap with test cannot be checked without opening test files.
5. A regime-stratified split by episode touches the campaign manifest and its labels files, the release manifests and digests, 24 role-view files, 3000 example files, the pinned Agent 2 and Agent 5 artifacts and their reports, the Agent 1 artifact, the chained fixtures built from the first train record, and several tests and documents (section 6).
6. Yes. `tools/campaign_run.py` and `verum.campaign.runner.run_campaign` generate new episodes from a seed, and `run_campaign(..., indices=[...])` can run chosen slots. There is no option to force a regime; the regime of a slot is drawn from its seed (section 7).

## 1. How the split is defined

### 1.1 Where

| What | Where |
|---|---|
| Rule (code) | `src/verum/campaign/splits.py`: constants at lines 26 to 31, `build_split_plan` at line 77, `split_of` at line 102, `_is_held` at line 109 |
| Where the rule is applied | `src/verum/campaign/runner.py`: `context` (lines 107 to 111) builds the plan from the first 2,000 slots of the plan; `completed_fields` (line 254) calls `split_of` when an episode completes and stores `split` in the episode record |
| What is recorded | `src/verum/campaign/runner.py` lines 503 to 505 write `held_out_units`, `validation_units`, `held_out_assets` and `held_out_share` into `data/campaign/evaluator/manifest.json`; each episode record carries `split`, `unit` and `strata` |
| Labels per split | `data/campaign/agent_visible/labels_train_validation.jsonl` (train and validation only), `data/campaign/evaluator/labels_test.jsonl`, `labels_all.jsonl` (D88) |
| Carried into the release | `data/reference_release_v2/verum_reference_v2/release_manifest.json` (field `split` of each of 3,000 records; `source_manifest_sha256` binds it to the campaign manifest), `examples/<split>/`, `role_views/<role>/<split>.jsonl.gz`, `role_views_manifest.json` |
| Release builder | `src/verum/training/dataset.py` (`SPLITS` at line 36; the split of each example is the split of its parent episode, lines 239, 312, 337, 526, 542) and `src/verum/training/packaging.py` |
| Documentation | `docs/design_decisions.md` D86 (line 1154), D155 (line 1283), D88 (labels visibility); `docs/dataset_card.md` lines 112 to 114; `docs/agent_data_contract.md` lines 24 to 28; `docs/data_generation.md` line 9 |
| Tests of the rule | `tests/regression/test_campaign.py` lines 258 (`test_held_out_strata_and_assets_never_reach_train_or_validation`) and 287; `tests/regression/test_campaign_rules.py` line 459 |

### 1.2 The rule

From `splits.py` and D86/D155:

- The unit of the split is the (family, atmosphere, temperature) triple. Units are ordered by a permutation drawn from the stream `campaign/splits` of the campaign seed.
- Test units: units holding at least 2.5% of the plan are added until together they hold at least 8% of the plan (shares measured on a reference prefix of 2,000 slots, so they do not depend on the target size).
- Validation units: from the remaining units, in the same random order, until they hold 30% of the remaining plan share.
- Train: everything else.
- Test also takes, whatever its unit, every episode that has a held-out (subtype, asset) pair: one asset per fault subtype (an asset and family pair for subtypes with fewer than four assets). A pair episode is test if either fault is held out.

I recomputed the plan from the code with the campaign configuration (seed 20261101, target 3,004) and compared it with the manifest: the two test units, the 11 validation units, the nine held-out assets and the held-out share 0.081 are **identical**.

| Split | Units | Episodes | Share of 3,000 | Windows (12 per episode) |
|---|---|---|---|---|
| train | 25 | 1660 | 55.3% | 19920 |
| validation | 11 | 756 | 25.2% | 9072 |
| test | 2 whole units (254 episodes) plus held-out assets in other units (330 episodes) | 584 | 19.5% | 7008 |

Test units: `concurrent|inland|35` and `receipt|coastal|25`. Held-out assets (`held_out_assets` in the manifest; second element is the family when a pair is held out):

| subtype | held-out asset | family |
|---|---|---|
| bias | FT-201 | - |
| drift | FT-201 | - |
| leak | E-SH | - |
| misroute_a | XV-S103 | - |
| misroute_b | XV-R102 | branched |
| pump | P-101A | delivery |
| restriction_obstruction | XV-R102 | - |
| restriction_position_visible | XV-R103 | - |
| stuck | PT-001 | - |

The 330 test episodes outside the two test units can only be there because of a held-out asset (that is what the rule says); I could not verify this per episode because it needs their fault labels, which I did not read. The reverse is verified: none of the 2416 train and validation episodes is in a test unit or has a held-out (subtype, asset) pair.

### 1.3 By episode, documented, intended

- **By episode.** Yes. One episode has one split; its 12 windows and its inspection children inherit it (`docs/agent_data_contract.md` line 26; `dataset.py` lines 526 and 542 refuse a release in which an example's split differs from its parent). In this release `parent_group` equals the episode id for all 28,992 train and validation windows.
- **Documented.** Yes: D86, D155, the dataset card and the data contract (table above). Not documented: the actual units, the share of each split per temperature, or that the train and validation temperature mixtures differ.
- **Intentional.** Yes. D86 states the reason ("Held-out strata test transfer to conditions not seen") and the rule splits the *remaining* units 70 to 30 into train and validation, so validation consists of whole units that train never sees. That the shares are "reached by the choice of units and are reported, not enforced per episode" is also stated (D86 notes). Observed: test 19.5% (target about 20%), validation 25.2%, train 55.3%.
- **Documentation drift.** D155 says "32 units (4 families, 2 atmospheres, 4 temperatures)"; the manifest has 38 units (5 families including `branched`, 2 atmospheres, 4 temperatures; 40 combinations, 38 occurring).

## 2. Correction to an earlier statement about temperature

On the branch `detector-experiment`, Amendment 1 of `reports/detector_experiment_plan.md` says train fault-free windows sit at 25, 35 and 45 C and that "40 degrees C was held out of training". **That is wrong.** I read percentiles of the temperature column and took the gap between two of them for a missing value. The campaign manifest and the windows show that train has all four temperatures (table in section 3.2); 40 C is present in train with 203 episodes and 1,010 fault-free eligible windows. What is true, and was the cause of the large z-scores, is that the **mixture** differs: eligible train fault-free windows are 54% at 25 C, validation has none at 25 C (the 54 validation episodes at 25 C are all `branched`, which has no eligible windows) and is 54% at 40 C. The sentence should be corrected there; I have not changed that branch.

## 3. Regimes by split

Columns "windows" are snapshots (12 per episode) and are the only window count I give for test. Eligible, fault-free and faulty counts need labels; they are given for train and validation only. The test episode counts come from the `split`, `unit` and `strata` fields of the manifest, read without any label field.

### 3.1 Units

| unit (family, atmosphere, temperature C) | role by the rule | episodes train | val | test | windows train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|---|---|---|---|
| branched|coastal|25 | validation unit | 0 | 31 | 9 | 0 | 372 | 108 | 0 | 0 | 0 | 0 |
| branched|coastal|35 | train unit | 25 | 0 | 11 | 300 | 0 | 132 | 0 | 0 | 0 | 0 |
| branched|coastal|40 | train unit | 14 | 0 | 5 | 168 | 0 | 60 | 0 | 0 | 0 | 0 |
| branched|inland|25 | validation unit | 0 | 23 | 7 | 0 | 276 | 84 | 0 | 0 | 0 | 0 |
| branched|inland|35 | validation unit | 0 | 29 | 3 | 0 | 348 | 36 | 0 | 0 | 0 | 0 |
| branched|inland|40 | train unit | 18 | 0 | 6 | 216 | 0 | 72 | 0 | 0 | 0 | 0 |
| concurrent|coastal|25 | train unit | 159 | 0 | 11 | 1908 | 0 | 132 | 725 | 146 | 0 | 0 |
| concurrent|coastal|35 | train unit | 117 | 0 | 4 | 1404 | 0 | 48 | 536 | 73 | 0 | 0 |
| concurrent|coastal|40 | validation unit | 0 | 86 | 5 | 0 | 1032 | 60 | 0 | 0 | 443 | 45 |
| concurrent|coastal|45 | train unit | 40 | 0 | 0 | 480 | 0 | 0 | 215 | 25 | 0 | 0 |
| concurrent|inland|25 | train unit | 163 | 0 | 14 | 1956 | 0 | 168 | 742 | 126 | 0 | 0 |
| concurrent|inland|35 | test unit | 0 | 0 | 114 | 0 | 0 | 1368 | 0 | 0 | 0 | 0 |
| concurrent|inland|40 | validation unit | 0 | 91 | 9 | 0 | 1092 | 108 | 0 | 0 | 423 | 72 |
| concurrent|inland|45 | train unit | 36 | 0 | 0 | 432 | 0 | 0 | 192 | 16 | 0 | 0 |
| delivery|coastal|25 | train unit | 162 | 0 | 20 | 1944 | 0 | 240 | 944 | 107 | 0 | 0 |
| delivery|coastal|35 | validation unit | 0 | 140 | 27 | 0 | 1680 | 324 | 0 | 0 | 717 | 121 |
| delivery|coastal|40 | validation unit | 0 | 86 | 14 | 0 | 1032 | 168 | 0 | 0 | 432 | 41 |
| delivery|coastal|45 | train unit | 31 | 0 | 8 | 372 | 0 | 96 | 151 | 14 | 0 | 0 |
| delivery|inland|25 | train unit | 182 | 0 | 22 | 2184 | 0 | 264 | 1012 | 144 | 0 | 0 |
| delivery|inland|35 | validation unit | 0 | 130 | 16 | 0 | 1560 | 192 | 0 | 0 | 690 | 87 |
| delivery|inland|40 | validation unit | 0 | 86 | 16 | 0 | 1032 | 192 | 0 | 0 | 431 | 103 |
| delivery|inland|45 | train unit | 35 | 0 | 11 | 420 | 0 | 132 | 151 | 28 | 0 | 0 |
| receipt|coastal|25 | test unit | 0 | 0 | 140 | 0 | 0 | 1680 | 0 | 0 | 0 | 0 |
| receipt|coastal|35 | train unit | 89 | 0 | 19 | 1068 | 0 | 228 | 446 | 87 | 0 | 0 |
| receipt|coastal|40 | train unit | 70 | 0 | 7 | 840 | 0 | 84 | 404 | 76 | 0 | 0 |
| receipt|coastal|45 | train unit | 24 | 0 | 0 | 288 | 0 | 0 | 168 | 9 | 0 | 0 |
| receipt|inland|25 | train unit | 134 | 0 | 21 | 1608 | 0 | 252 | 751 | 90 | 0 | 0 |
| receipt|inland|35 | train unit | 86 | 0 | 15 | 1032 | 0 | 180 | 448 | 99 | 0 | 0 |
| receipt|inland|40 | train unit | 72 | 0 | 8 | 864 | 0 | 96 | 401 | 84 | 0 | 0 |
| receipt|inland|45 | validation unit | 0 | 29 | 1 | 0 | 348 | 12 | 0 | 0 | 171 | 18 |
| switch|coastal|25 | train unit | 44 | 0 | 10 | 528 | 0 | 120 | 258 | 21 | 0 | 0 |
| switch|coastal|35 | train unit | 36 | 0 | 8 | 432 | 0 | 96 | 228 | 27 | 0 | 0 |
| switch|coastal|40 | validation unit | 0 | 25 | 4 | 0 | 300 | 48 | 0 | 0 | 177 | 9 |
| switch|coastal|45 | train unit | 10 | 0 | 1 | 120 | 0 | 12 | 66 | 8 | 0 | 0 |
| switch|inland|25 | train unit | 39 | 0 | 6 | 468 | 0 | 72 | 219 | 34 | 0 | 0 |
| switch|inland|35 | train unit | 32 | 0 | 5 | 384 | 0 | 60 | 198 | 25 | 0 | 0 |
| switch|inland|40 | train unit | 29 | 0 | 5 | 348 | 0 | 60 | 205 | 14 | 0 | 0 |
| switch|inland|45 | train unit | 13 | 0 | 2 | 156 | 0 | 24 | 119 | 0 | 0 | 0 |

Totals: 25 train units, 11 validation units, 2 test units; train fault-free eligible 8,579 and faulty 1,253; validation fault-free eligible 3,484 and faulty 496.

### 3.2 Set points one at a time

**Temperature (C)**

| temperature | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| 25.0 | 883 | 54 | 260 | 4651 | 668 | 0 | 0 |
| 35.0 | 385 | 299 | 222 | 1856 | 311 | 1407 | 208 |
| 40.0 | 203 | 374 | 79 | 1010 | 174 | 1906 | 270 |
| 45.0 | 189 | 29 | 23 | 1062 | 100 | 171 | 18 |

**Atmosphere**

| atmosphere | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| coastal | 821 | 368 | 303 | 4141 | 593 | 1769 | 216 |
| inland | 839 | 388 | 281 | 4438 | 660 | 1715 | 280 |

**Family**

| family | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| branched | 57 | 83 | 41 | 0 | 0 | 0 | 0 |
| concurrent | 515 | 177 | 157 | 2410 | 386 | 866 | 117 |
| delivery | 410 | 442 | 134 | 2258 | 293 | 2270 | 352 |
| receipt | 475 | 29 | 211 | 2618 | 445 | 171 | 18 |
| switch | 203 | 25 | 41 | 1293 | 129 | 177 | 9 |

**Flow set point (m3/h)**

| setpoint | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| 300.0 | 417 | 174 | 147 | 2171 | 299 | 789 | 128 |
| 400.0 | 424 | 184 | 127 | 2108 | 306 | 912 | 123 |
| 500.0 | 430 | 212 | 172 | 2216 | 331 | 861 | 123 |
| 600.0 | 389 | 186 | 138 | 2084 | 317 | 922 | 122 |

**Stress flag (stress episodes run at 45 C)**

| stress | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| False | 1471 | 727 | 561 | 7517 | 1153 | 3313 | 478 |
| True | 189 | 29 | 23 | 1062 | 100 | 171 | 18 |

Eligible fault-free windows by temperature, share of the split:

| split | 25 C | 35 C | 40 C | 45 C |
|---|---|---|---|---|
| train | 54.2% (4651) | 21.6% (1856) | 11.8% (1010) | 12.4% (1062) |
| validation | 0.0% (0) | 40.4% (1407) | 54.7% (1906) | 4.9% (171) |

**Lineup mode** (the campaign's operating mode; `branched` is `RECEIVE_101_102`):

| mode | episodes train | val | test | train fault-free eligible | train faulty eligible | val fault-free eligible | val faulty eligible |
|---|---|---|---|---|---|---|---|
| DELIVER_101_A | 57 | 68 | 36 | 308 | 35 | 352 | 62 |
| DELIVER_101_B | 74 | 83 | 12 | 369 | 57 | 387 | 53 |
| DELIVER_102_A | 62 | 58 | 35 | 341 | 15 | 329 | 38 |
| DELIVER_102_B | 82 | 79 | 13 | 413 | 78 | 347 | 57 |
| DELIVER_103_A | 70 | 78 | 32 | 425 | 38 | 415 | 66 |
| DELIVER_103_B | 74 | 89 | 16 | 402 | 70 | 440 | 76 |
| RECEIVE_101 | 248 | 26 | 62 | 1369 | 249 | 137 | 9 |
| RECEIVE_101_102 | 38 | 52 | 31 | 0 | 0 | 0 | 0 |
| RECEIVE_101_DELIVER_101_A | 265 | 98 | 93 | 1242 | 179 | 467 | 70 |
| RECEIVE_101_DELIVER_102_A | 250 | 79 | 64 | 1168 | 207 | 399 | 47 |
| RECEIVE_102 | 216 | 20 | 104 | 1266 | 182 | 86 | 9 |
| RECEIVE_103 | 224 | 26 | 86 | 1276 | 143 | 125 | 9 |

### 3.3 Fault types by regime (train and validation, eligible windows)

Fault types: restriction (both restriction subtypes), pump, bias, drift, stuck, leak, misrouting, multi (more than one injected component). Test fault types are labels and were not read.

**By temperature**

| split | temperature C | fault-free | restriction | pump | bias | drift | stuck | leak | misrouting | multi |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 25 | 4651 | 260 | 53 | 65 | 106 | 56 | 54 | 3 | 71 |
| train | 35 | 1856 | 146 | 12 | 27 | 41 | 12 | 36 | 0 | 37 |
| train | 40 | 1010 | 63 | 0 | 34 | 25 | 0 | 41 | 0 | 11 |
| train | 45 | 1062 | 21 | 4 | 6 | 25 | 11 | 15 | 6 | 12 |
| validation | 25 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| validation | 35 | 1407 | 85 | 36 | 33 | 8 | 7 | 18 | 12 | 9 |
| validation | 40 | 1906 | 71 | 36 | 26 | 42 | 26 | 31 | 3 | 35 |
| validation | 45 | 171 | 0 | 0 | 10 | 0 | 0 | 8 | 0 | 0 |

**By family**

| split | family | fault-free | restriction | pump | bias | drift | stuck | leak | misrouting | multi |
|---|---|---|---|---|---|---|---|---|---|---|
| train | branched | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| train | concurrent | 2410 | 155 | 32 | 21 | 43 | 21 | 36 | 0 | 78 |
| train | delivery | 2258 | 104 | 37 | 34 | 59 | 19 | 18 | 9 | 13 |
| train | receipt | 2618 | 158 | 0 | 65 | 68 | 31 | 83 | 0 | 40 |
| train | switch | 1293 | 73 | 0 | 12 | 27 | 8 | 9 | 0 | 0 |
| validation | branched | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| validation | concurrent | 866 | 19 | 31 | 0 | 18 | 17 | 3 | 0 | 29 |
| validation | delivery | 2270 | 137 | 41 | 58 | 24 | 16 | 46 | 15 | 15 |
| validation | receipt | 171 | 0 | 0 | 10 | 0 | 0 | 8 | 0 | 0 |
| validation | switch | 177 | 0 | 0 | 1 | 8 | 0 | 0 | 0 | 0 |

### 3.4 Lineup states (signal level)

Lineup states come from window signals, so only train and validation can be tabulated. The 12 states below are the only ones with fault-free windows.

| state (16 on/off tags in the order LSHH-101..103, P-101A, P-101B, XV-PAI, XV-PAO, XV-PBI, XV-PBO, XV-R000, XV-R101..103, XV-S101..103) | dominant mode | train fault-free | val fault-free | train faulty | val faulty |
|---|---|---|---|---|---|
| 0001011001100100 | RECEIVE_101_DELIVER_101_A | 1242 | 467 | 114 | 41 |
| 0000000001100000 | RECEIVE_101 | 1227 | 101 | 154 | 5 |
| 0000000001001000 | RECEIVE_103 | 1179 | 129 | 132 | 10 |
| 0001011001100010 | RECEIVE_101_DELIVER_102_A | 1168 | 399 | 104 | 38 |
| 0000000001010000 | RECEIVE_102 | 1099 | 68 | 87 | 12 |
| 0001011000000001 | DELIVER_103_A | 425 | 415 | 20 | 25 |
| 0000100110000010 | DELIVER_102_B | 413 | 347 | 46 | 28 |
| 0000000000000000 | RECEIVE_101 | 406 | 50 | 0 | 0 |
| 0000100110000001 | DELIVER_103_B | 402 | 440 | 34 | 50 |
| 0000100110000100 | DELIVER_101_B | 369 | 387 | 33 | 31 |
| 0001011000000010 | DELIVER_102_A | 341 | 329 | 14 | 29 |
| 0001011000000100 | DELIVER_101_A | 308 | 352 | 24 | 27 |
| 26 other states | (fault states) | 0 | 0 | 491 | 200 |

## 4. Regimes with fewer than 200 fault-free train windows

Three levels, because "regime" can mean three things.

**(a) Unit (family, atmosphere, temperature).** 23 of 38 units have fewer than 200 eligible fault-free train windows:

| unit | role by the rule | train fault-free eligible |
|---|---|---|
| branched|coastal|35 | train | 0 |
| branched|coastal|40 | train | 0 |
| branched|inland|40 | train | 0 |
| switch|coastal|45 | train | 66 |
| switch|inland|45 | train | 119 |
| delivery|coastal|45 | train | 151 |
| delivery|inland|45 | train | 151 |
| receipt|coastal|45 | train | 168 |
| concurrent|inland|45 | train | 192 |
| switch|inland|35 | train | 198 |
| branched|coastal|25 | validation | 0 |
| branched|inland|25 | validation | 0 |
| branched|inland|35 | validation | 0 |
| concurrent|coastal|40 | validation | 0 |
| concurrent|inland|35 | test | 0 |
| concurrent|inland|40 | validation | 0 |
| delivery|coastal|35 | validation | 0 |
| delivery|coastal|40 | validation | 0 |
| delivery|inland|35 | validation | 0 |
| delivery|inland|40 | validation | 0 |
| receipt|coastal|25 | test | 0 |
| receipt|inland|45 | validation | 0 |
| switch|coastal|40 | validation | 0 |

All 13 validation and test units have 0 by construction. The ten train units in the list are three `branched` units (no eligible windows at all) and seven small ones: `concurrent|inland|45` (192), `delivery|coastal|45` and `delivery|inland|45` (151 each), `receipt|coastal|45` (168), `switch|coastal|45` (66), `switch|inland|45` (119) and `switch|inland|35` (198). The faulty windows of train and validation in these units: validation units hold 496 faulty windows in total, every one of them in a unit that train has never seen.

**(b) Mode.** Fault-free eligible train windows per mode, and episodes per split (test episodes from the manifest `strata.mode` only):

| mode | train fault-free eligible | <200? | episodes train | val | test |
|---|---|---|---|---|---|
| DELIVER_101_A | 308 | no | 57 | 68 | 36 |
| DELIVER_101_B | 369 | no | 74 | 83 | 12 |
| DELIVER_102_A | 341 | no | 62 | 58 | 35 |
| DELIVER_102_B | 413 | no | 82 | 79 | 13 |
| DELIVER_103_A | 425 | no | 70 | 78 | 32 |
| DELIVER_103_B | 402 | no | 74 | 89 | 16 |
| RECEIVE_101 | 1369 | no | 248 | 26 | 62 |
| RECEIVE_101_102 | 0 | yes | 38 | 52 | 31 |
| RECEIVE_101_DELIVER_101_A | 1242 | no | 265 | 98 | 93 |
| RECEIVE_101_DELIVER_102_A | 1168 | no | 250 | 79 | 64 |
| RECEIVE_102 | 1266 | no | 216 | 20 | 104 |
| RECEIVE_103 | 1276 | no | 224 | 26 | 86 |

Only `RECEIVE_101_102` (the branched lineup) is below 200 (0 windows). It has 31 test episodes, 52 validation and 38 train episodes, none with an eligible window in train or validation (family `branched`).

**(c) Lineup state (signal level; the definition used by the detector experiment).** 12 states have 200 or more fault-free train windows (every fault-free train window, 8,579, is in one of them). The other 26 states seen in eligible train and validation windows have 0 fault-free windows in either split. Faulty eligible windows by type, in the 12 common states and in the 26 other states:

| fault type | train: common | other | validation: common | other | train+validation: common | other |
|---|---|---|---|
| restriction | 85 | 405 | 1 | 155 | 86 | 560 |
| pump | 69 | 0 | 72 | 0 | 141 | 0 |
| bias | 132 | 0 | 69 | 0 | 201 | 0 |
| drift | 197 | 0 | 50 | 0 | 247 | 0 |
| stuck | 79 | 0 | 33 | 0 | 112 | 0 |
| leak | 146 | 0 | 57 | 0 | 203 | 0 |
| misrouting | 0 | 9 | 0 | 15 | 0 | 24 |
| multi | 54 | 77 | 14 | 30 | 68 | 107 |

- Fault types that live **only** in the 26 other states: **misrouting** (24 windows).
- **Mostly** there: **restriction** (560 of 646 windows, 87%; in validation 155 of 156) and multi-fault windows (107 of 175).
- Pump, bias, drift, stuck and leak windows all lie in the 12 common states.
- These 26 states are not set points. They are lineups in which valve states differ from every fault-free lineup, that is, the visible effect of the fault itself (the restriction mode is called `position_visible`; misrouting changes valve states). So a rule on "unseen lineup" would be a fault label in disguise. A regime-stratified split cannot put fault-free windows into these states; it can only decide how many such fault windows each split gets.
- For the test split the same table cannot be built from metadata: lineup states need signals, and fault types need labels.

## 5. Overlap across splits

| Check | Result | Source |
|---|---|---|
| Episode ids shared by two splits | 0 for each pair (train-validation, train-test, validation-test) | `manifest.json`, `release_manifest.json` records, file names in `examples/<split>/` (listed, not opened); the three sources agree and equal the 3,000 folders in `observations/` |
| Episodes without a split | 4, all `status: gap` (the four incomplete slots), absent from the release | `manifest.json`, `gaps` |
| Episode seeds shared | 0 duplicates among the 3,000 completed episodes (the four gaps have no seed) | `manifest.json` field `seed` |
| Duplicate observation / source observation / example file digests | 0 / 0 / 0 over 3,000 records | `release_manifest.json` |
| Window ids shared by train and validation | 0 of 19,920 and 9,072 | role view `diagnostic_reasoning` |
| Parent groups shared by train and validation | 0; `parent_group` equals the episode id for every window | example lineage |
| Windows per episode | exactly 12 in train and in validation | role view |
| Labels file against manifest split | 0 disagreements over 2,416 labelled episodes; no test id in the file | `labels_train_validation.jsonl` |
| Train or validation episode in a test unit, or with a held-out asset | 0 | manifest |
| Train episode in a validation unit, validation episode outside one | 0, 0 | manifest |
| Test windows against train or validation windows | not checked at window level (needs the test example files); by construction a window belongs to one episode and episodes are disjoint | - |

What overlap does exist, by design: the same equipment, tags, catalogue and public facts occur in every split; roles 3, 4 and 6 serve static reference fixtures in all splits (`docs/agent_data_contract.md` line 28); and the same factor levels (all four temperatures, both atmospheres, all families) occur in train, only their combinations are held out.

## 6. What a regime-stratified split by episode would touch

A split by episode that keeps every unit in several splits needs a new `build_split_plan`/`split_of` rule (or a re-assignment of the existing 3,000 episodes, which needs no new simulation, because the split is only a field and a file layout). Everything below depends on the current assignment.

### 6.1 Campaign and release files

| File or folder | What depends on the split | Digest or count to change |
|---|---|---|
| `src/verum/campaign/splits.py`, `src/verum/campaign/runner.py` (lines 110, 254, 503 to 505) | the rule and where it is applied and recorded | rule; manifest keys `held_out_units`, `validation_units`, `held_out_assets`, `held_out_share` |
| `data/campaign/evaluator/manifest.json` | `split` of 3,000 episodes; held-out lists | sha256 `93e39275...b464`; cited by the release as `source_manifest_sha256` |
| `data/campaign/evaluator/records/` (one record per slot) | `split` inside each record (written when the episode completed) | 3,004 record files (not opened) |
| `data/campaign/agent_visible/labels_train_validation.jsonl`, `evaluator/labels_test.jsonl`, `labels_all.jsonl` | which labels are visible to agents (D88) | rows move between the files; an episode absent from the first is a test episode (README) |
| `data/campaign/agent_visible/episodes/`, `evaluator/episodes/` | none (observations and truth are per episode) | no change |
| `data/reference_release_v2/verum_reference_v2/release_manifest.json` | `split` and `example_file` of 3,000 records; `splits` counts 1660/756/584 | `source_manifest_sha256`; every `example_sha256` |
| `.../generation_recipe.json` | `source_manifest_sha256`, `inspection_source_manifest_sha256` | two hashes |
| `.../examples/{train,validation,test}/EP-*.jsonl.gz` (3,000 files) | folder = split; lineage field `split` | files move, and each example carries its split in `lineage.split`, so the file content and its `example_sha256` change too |
| `.../role_views/<role>/<split>.jsonl.gz` (24 files) and `role_views_manifest.json` | rows by split | 24 sha256 values and row counts (for example 19,920 / 9,072 / 7,008 windows for roles 1 and 2) |
| `.../release_summary.json`, `agent_data_contract.json` | counts per split | counts |
| training archive (`BUNDLE_FILES.json`, `.sha256.json`; `docs/data_generation.md` lines 7 to 17) | bundles the 24 role views and counts | archive checksum |
| `config/extensions/reference_recipe_v2.json` | campaign seed and target (3,004); not the split itself | unchanged unless the campaign is re-run |
| `tools/dataset_release.py`, `src/verum/training/dataset.py`, `packaging.py` | build, verify and package the release | re-run `build`, `materialize-all`, `verify`, `package` |

### 6.2 Trained artifacts and their reports (Agents 1, 2, 5)

| Artifact or report | Dependence | Evidence |
|---|---|---|
| Agent 1: `src/verum/agents/predictive_health/ridge_models.json` | trained on the train role view; the file records `training_sha256` = hash of `role_views/predictive_health/train.jsonl.gz` (`5792e6e0...`) | also `tools/agents/evaluate_predictive_health.py` line 30: "Originally selected on validation; FT-201 was removed after reviewing test" (the test split has already influenced a choice) |
| Agent 2: `src/verum/agents/anomaly_detection/artifacts/anomaly_detection_model.joblib` | fitted on train, threshold chosen on validation; sha256 pinned in `agent.py` line 97 (`EXPECTED_ARTIFACT_SHA256`) | `tools/agents/train_anomaly_detection.py`; reports `tools/agents/anomaly_detection_artifacts/evaluation_report.json` (9,832 / 3,980 windows) and `test_report.json` (the one-time test run, guard at line 309) |
| Agent 5: `src/verum/agents/diagnostic_reasoning/model_artifact.joblib` | fitted on train, thresholds on validation; sha256 pinned in `model.py` line 31 (`PINNED_ARTIFACT_SHA256`) | `tools/agents/diagnostic_reasoning_train.py` (loads train, validation and test, lines 319 to 323) |
| Agent 5: `src/verum/agents/diagnostic_reasoning/evaluation_report.json` | contains train, validation and test window and episode counts (9,832 / 3,980 / 2,828 windows; 1,603 / 673 / 543 episodes) and per-mechanism test results | also quoted in limitation text built by `rules.py` (lines 121 to 184: baseline exact-set accuracy 0.8225 on the test split) |
| Agents 3, 4, 6, 7, 8 | no trained artifact; Agent 8 evaluation (`tests/agents/evidence_verification_decision/test_evaluation.py`) and the reference-input tools read role views | the evaluation tests skip when the dataset is absent |

### 6.3 Fixtures, tests and documents

| File | Dependence |
|---|---|
| `tests/agents/fixtures/chained/*.json` (17 files), built by `tools/agents/build_chained_fixtures.py` | the first record of `role_views/predictive_health/train.jsonl.gz` (`next(iter_role_records(release, ROLE, "train"))`, line 29). Any change of the train file order or membership changes the fixtures; `build_chained_fixtures.py --check` then reports them stale. They must be regenerated deliberately, not silently |
| `contracts/agents/v1/examples/*.request.json` | carry the same real window values (for example FT-001 latest value 598.5442893...); they do not carry episode ids. Not regenerated by any script I found; not stale-checked against the data |
| `tests/regression/test_supported_release.py` (line 215: target 3,004), `test_campaign.py`, `test_campaign_rules.py`, `test_campaign_run.py`, `test_vapour_campaign.py`, `test_seeds.py` (seed 20261101) | campaign configuration and rule; they test the rule by code, not the stored data. A new rule needs new tests (`test_campaign.py` lines 258 and 287, `test_campaign_rules.py` line 459 encode the current rule) |
| `tests/agents/evidence_verification_decision/test_evaluation.py` | reads the real release and skips if it is absent (lines 17, 30, 47) |
| `tests/agents/common/test_agent_common_observations_loader.py`, `tests/agents/diagnostic_reasoning/test_diagnostic_reasoning_stub.py` | use small synthetic releases built in a temporary folder; no dependence on the real assignment |
| `src/verum/agents/common/loader.py` | verifies each role-view file against `role_views_manifest.json` before reading (`_check_role_file`) |
| `docs/agent_interfaces.md` (counts 756, 584, 9,832; "Keep the existing split" at line 195), `docs/dataset_card.md`, `docs/data_generation.md`, `docs/design_decisions.md` D86, D155, `docs/agent_data_contract.md` lines 24 to 28 | state the rule and counts |
| `reports/` of the branch `detector-experiment` (`tools/detector/*`, plan and results) | use train and validation as defined now; their numbers would change |
| `uv.lock` (1,132 lines), `vendor/MANIFEST.sha256` | no dependence on the split (dependencies and vendored schemas) |

Not dependent on the split: the physical configuration under `config/` (its hash `beb8429d...` is in the release but covers the model, not the assignment), the observation and truth files of each episode, and `contracts/` schemas.

## 7. Can new episodes be generated in every regime?

Yes, with limits.

| Item | Fact | Where |
|---|---|---|
| Generator | the campaign runner; the CLI is `tools/campaign_run.py` (`--root`, `--seed`, `--n`, `--workers`, `--stop-after-hours`) | `tools/campaign_run.py`, `src/verum/campaign/runner.py` `run_campaign` |
| Seeds | a slot's episode seed is a function of the campaign seed, the slot index and the attempt (`episode_seed(seed, slot * 5 + attempt)`); a new campaign seed or a larger `--n` gives fresh episodes; a rerun with the same inputs reproduces stored hashes (`verify_sample`, D87) | `plan.py` (`EPISODE_STRIDE`), `sampler.py`, `runner.py` (`regenerate`, `verify_sample`) |
| Regime control | the regime of a slot is drawn, not chosen: `Sampler.cell` draws atmosphere (coastal or inland), temperature (25, 35 or 40 C with weights 0.435, 0.326, 0.239; 45 C for stress slots) and the family from the slot's stream; the lineup, flow set point (300, 400, 500 or 600 m3/h) and initial levels are drawn per attempt. There is **no parameter that forces a unit** | `sampler.py` lines 51 to 60, 169 to 190 |
| Choosing slots | `run_campaign(config, root, workers, indices=[...])` runs only the listed slot indices. A caller can compute `Sampler.cell(slot)` for many slots (cheap: no simulation), keep those whose unit is wanted, and run only them. No CLI option exposes this; it would be a new script | `runner.py` lines 346 to 380 |
| Extending | a larger `--n` appends whole blocks of 100 slots and keeps the finished ones; the split plan stays the same because it is measured on the first 2,000 slots, so new episodes are assigned by the current rule | `plan.py`, `splits.py` |
| Inputs needed | `CampaignConfig(seed, n, block, duration_s)` (stored in `campaign_config.json`); the physical configuration under `config/` (scenarios `S0-*`, `sim.json`, `lineups.json`, `hydraulics.json`, sensor and severity tables, `audit_cells.json`, tank geometry, and the pumping-minimum tables per atmosphere and stratum); the class table and audit cells; no data from `data/` | `runner.context`, `sampler.py` |
| Cost | one episode took 48.9 s mean wall time; the 3,004-slot campaign wrote 1.79 GB agent-visible and 2.10 GB evaluator data (`accounting.json`, from the four-slot final run). At the default 4 to 6 workers (cores minus 2, at most 6) 3,000 episodes need roughly 7 to 10 hours; the runner refuses to start with less than 20 GB free | `runner.py` lines 45 to 46, 78 to 90 |
| After generating | rebuild the release: `tools/dataset_release.py build`, `materialize-all`, `verify`, `package`; each new release has its own manifests and digests, and the trained artifacts must be retrained and re-pinned | `tools/dataset_release.py` |

What is not available for the fault-only lineup states of section 4: a new episode cannot place a fault-free window in them, because the states are produced by the faults.

## 8. What I read and did not read

- Opened as data: the campaign manifest (`manifest.json`), `accounting.json`, `campaign_config.json`, `labels_train_validation.jsonl`, `release_manifest.json`, `role_views_manifest.json`, `generation_recipe.json`, the `diagnostic_reasoning` role view and the example files of **train and validation** (for window counts, labels and lineage), and the public reference. An audit hook (allow-list) was installed for the run and would have raised on any other file under `data/`; it did not.
- Not opened: `labels_test.jsonl`, `labels_all.jsonl`, any file under `examples/test/`, `role_views/*/test.jsonl.gz`, test observation files, `evaluator/episodes/` and `evaluator/records/`. Directory listings of `examples/test/` and `observations/` were read for episode ids (names only).
- Limitation of the manifest read: `manifest.json` holds the fault labels of test episodes in the same records as their `split` and `unit`. The file was parsed whole; for test episodes only `episode_id`, `split`, `unit`, `strata`, `status`, `seed`, `index` and `attempt` were kept and used, and the label fields (`faults`, `cell`, `kind`, `subtypes`, `classes`) were dropped without being printed or used. `release_manifest.json` was parsed whole and only `snapshots` was used from the per-episode counts of test episodes.
- Manifest counts for the test split that are label-derived (eligible and positive windows in `role_views_manifest.json`) were not used.
- Test-split facts that remain unknown to this audit: fault types and fault-free windows per regime, window-level overlap, and whether each of the 330 test episodes outside the test units has a held-out asset.

## 9. Observations for later decisions

- Validation measures transfer to unseen unit combinations by design. A selection or threshold made on it inherits that shift (the detector experiment hit this through the temperature mixture).
- The test split has already been consulted by the authors of Agents 1, 2 and 5 (section 6.2: a test-based feature removal in Agent 1, a one-time test report for Agent 2, test counts and metrics in the Agent 5 report and limitation text). A new test would therefore need freshly generated episodes, not only a reassignment.
- Restriction and misrouting faults are visible in the lineup states themselves; any regime-based stratification must treat those states as fault signal, not as an operating condition.
