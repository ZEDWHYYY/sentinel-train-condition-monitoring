# Model card — ACV

- **Version:** `acv-A0-1.0.0`
- **Method:** Peer/target cooling-residual ranking (`A0`)
- **Created:** 2026-09-18T23:34:29
- **Training fingerprint:** `444e4cc4e4c8c4e2…`
- **Official metric:** Linear rank-decay (n − r + 1)/n, mean over cases (official)
- **Local validation (leave-one-case-out, 6 cases):** Rank-decay score = 0.979

These are local development-validation figures on the supplied training data. They are not organizer results and do not guarantee held-out performance.

## Protocol

Leave-one-case-out over 6 training cases. A0 and A1 are fixed, preregistered rules with no fitted weights, so no tuning occurs inside folds; LOO scores equal per-case scores.

## Candidates compared

| Candidate | Per-case rank of true car | Mean score | Top-1 | Top-3 |
|---|---|---|---|---|
| A0 | acv_case_01: 1, acv_case_02: 1, acv_case_03: 1, acv_case_04: 2, acv_case_05: 1, acv_case_06: 1 | 0.979 | 5/6 | 6/6 |
| A1 | acv_case_01: 1, acv_case_02: 1, acv_case_03: 1, acv_case_04: 2, acv_case_05: 1, acv_case_06: 1 | 0.979 | 5/6 | 6/6 |

Score definition: Mean over valid, settled active-cooling samples of (car cabin temperature − median cabin temperature of the other cooling cars at the same time), in K.
Permutation test (relabel cars within a case): passed.
Held-out schema: sheet `故障案例3-0620_20210624`, 67 columns, cars 01, 02, 03, 04, 05, 06, 07, 08.

Selection rule: Higher mean LOO score; ties go to the simpler A0.

## Known limitations

- Six cases are six independent fault examples; ranking generalisation is weakly evidenced.
- Case 04 uses a rich schema; its indoor/target/mode signals come from recorded aliases, and cars 05–08 have no data.
- Cases 05 and 06 have no outdoor temperature; the ranker does not use outdoor temperature.
- Scores are relative evidence among cars in one case, not leak probabilities.

## Environment

- python: 3.13.6
- numpy: 2.5.3
- pandas: 3.0.6
- scipy: 1.18.1
- scikit-learn: 1.9.1
- platform: macOS-27.0-arm64-arm-64bit-Mach-O
