# Regime key: evidence for Amendment 2

## The key of the first experiment

The regime key behind the 200-window guard and the per-regime baselines of C1, C2 and C3 (R4) was the state of the 16 on/off tags of the window, taken from `latest_value`: LSHH-101, LSHH-102, LSHH-103, P-101A, P-101B, XV-PAI, XV-PAO, XV-PBI, XV-PBO, XV-R000, XV-R101, XV-R102, XV-R103, XV-S101, XV-S102, XV-S103. These are level switches, pump run states and valve contact states. A fault can change them: the restriction mode `position_visible` and misrouting act on valve positions.

Windows whose key no fault-free train window has, and windows whose key differs from the most common key of the same episode's fault-free windows (own-episode change):

| split | fault type | windows | key never fault-free | own-episode change | tags that differ from the nearest fault-free key |
|---|---|---|---|---|---|
| train | restriction | 490 | 405 | 416/490 | XV-R000 217, XV-PBO 44, XV-S103 38, XV-PAO 35, XV-PAI 31, XV-S102 23 |
| train | pump | 69 | 0 | 0/69 | - |
| train | bias | 132 | 0 | 12/132 | - |
| train | drift | 197 | 0 | 27/197 | - |
| train | stuck | 79 | 0 | 8/79 | - |
| train | leak | 146 | 0 | 9/146 | - |
| train | misrouting | 9 | 9 | 9/9 | XV-PBI 9 |
| train | multi | 131 | 77 | 77/131 | XV-R000 53, XV-PAO 13, XV-PAI 10, XV-S102 9, XV-S103 8, XV-PBO 6 |
| validation | restriction | 156 | 155 | 155/156 | XV-PAO 35, XV-S103 33, XV-PBO 32, XV-PAI 28, XV-PBI 22, XV-R000 3 |
| validation | pump | 72 | 0 | 0/72 | - |
| validation | bias | 69 | 0 | 1/69 | - |
| validation | drift | 50 | 0 | 8/50 | - |
| validation | stuck | 33 | 0 | 0/33 | - |
| validation | leak | 57 | 0 | 0/57 | - |
| validation | misrouting | 15 | 15 | 15/15 | XV-PBI 15 |
| validation | multi | 44 | 30 | 30/44 | XV-S103 12, XV-R000 9, XV-PAI 6, XV-S102 6, XV-PBI 1 |

Restriction and misrouting windows carry a key that no fault-free window has, and the differing tags are valve states (`XV-*`). Pump, bias, drift, stuck and leak windows have keys that fault-free windows also have. So the key contains fault effects for two fault types, and a baseline or guard built on it separates those windows by construction.

## The new key: operator-set conditions

Atmosphere, temperature and flow set point of the episode. The stress flag is a set condition and equals temperature 45 C in every episode ({'(False, False)': 2058, '(True, True)': 218}), so it adds nothing to the key. A fault changes none of these fields.

| atmosphere / temperature C / set point m3/h | episodes train | episodes validation | train fault-free | train faulty | validation fault-free | validation faulty | own baseline (200 or more train fault-free) |
|---|---|---|---|---|---|---|---|
| coastal / 25.0 / 300.0 | 87 | 0 | 498 | 62 | 0 | 0 | yes |
| coastal / 25.0 / 400.0 | 100 | 0 | 540 | 49 | 0 | 0 | yes |
| coastal / 25.0 / 500.0 | 104 | 0 | 497 | 94 | 0 | 0 | yes |
| coastal / 25.0 / 600.0 | 74 | 0 | 392 | 69 | 0 | 0 | yes |
| coastal / 35.0 / 300.0 | 49 | 29 | 224 | 34 | 146 | 36 | yes |
| coastal / 35.0 / 400.0 | 67 | 36 | 334 | 47 | 183 | 25 | yes |
| coastal / 35.0 / 500.0 | 60 | 37 | 284 | 73 | 165 | 34 | yes |
| coastal / 35.0 / 600.0 | 66 | 38 | 368 | 33 | 223 | 26 | yes |
| coastal / 40.0 / 300.0 | 20 | 47 | 121 | 25 | 225 | 14 | no |
| coastal / 40.0 / 400.0 | 16 | 55 | 86 | 13 | 303 | 23 | no |
| coastal / 40.0 / 500.0 | 18 | 47 | 114 | 16 | 255 | 18 | no |
| coastal / 40.0 / 600.0 | 16 | 48 | 83 | 22 | 269 | 40 | no |
| coastal / 45.0 / 300.0 | 26 | 0 | 143 | 21 | 0 | 0 | no |
| coastal / 45.0 / 400.0 | 23 | 0 | 121 | 6 | 0 | 0 | no |
| coastal / 45.0 / 500.0 | 27 | 0 | 177 | 2 | 0 | 0 | no |
| coastal / 45.0 / 600.0 | 29 | 0 | 159 | 27 | 0 | 0 | no |
| inland / 25.0 / 300.0 | 149 | 0 | 803 | 104 | 0 | 0 | yes |
| inland / 25.0 / 400.0 | 128 | 0 | 622 | 107 | 0 | 0 | yes |
| inland / 25.0 / 500.0 | 123 | 0 | 640 | 95 | 0 | 0 | yes |
| inland / 25.0 / 600.0 | 118 | 0 | 659 | 88 | 0 | 0 | yes |
| inland / 35.0 / 300.0 | 31 | 35 | 148 | 28 | 189 | 29 | no |
| inland / 35.0 / 400.0 | 26 | 27 | 116 | 42 | 163 | 12 | no |
| inland / 35.0 / 500.0 | 35 | 38 | 223 | 22 | 171 | 27 | yes |
| inland / 35.0 / 600.0 | 26 | 30 | 159 | 32 | 167 | 19 | no |
| inland / 40.0 / 300.0 | 17 | 40 | 93 | 18 | 198 | 44 | no |
| inland / 40.0 / 400.0 | 30 | 46 | 173 | 42 | 234 | 63 | no |
| inland / 40.0 / 500.0 | 28 | 48 | 193 | 17 | 204 | 41 | no |
| inland / 40.0 / 600.0 | 26 | 43 | 147 | 21 | 218 | 27 | no |
| inland / 45.0 / 300.0 | 25 | 6 | 141 | 7 | 31 | 5 | no |
| inland / 45.0 / 400.0 | 21 | 3 | 116 | 0 | 29 | 0 | no |
| inland / 45.0 / 500.0 | 16 | 10 | 88 | 12 | 66 | 3 | no |
| inland / 45.0 / 600.0 | 22 | 10 | 117 | 25 | 45 | 10 | no |

32 regimes occur; 13 have 200 or more fault-free train windows and hold 6084 of 8579 fault-free train windows. 2944 of 3980 validation windows are in regimes without an own baseline and use the pooled baseline.
