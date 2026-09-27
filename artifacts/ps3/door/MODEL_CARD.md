# Model card — DOOR

- **Version:** `door-D2-1.1.0`
- **Method:** Gap segmentation + direction-conditioned current-integral rule relative to the recording's own baseline (`D2`)
- **Created:** 2026-09-19T01:29:05
- **Training fingerprint:** `1e28518a874afe3f…`
- **Official metric:** IoU-weighted F1 (official)
- **Local validation (5 contiguous-block CV, full pipeline):** IoU-weighted F1 = 0.991

These are local development-validation figures on the supplied training data. They are not organizer results and do not guarantee held-out performance.

## Protocol

5 contiguous blocks of the continuous Train stream; for each block, rules fitted on the other blocks and the full segmenter + direction + classifier pipeline run on the held-out block's rows.

## Candidates compared

| Candidate | Fold scores | Mean | Mean under synthetic current shifts |
|---|---|---|---|
| D0 | 0.955, 1.000, 1.000, 1.000, 1.000 | 0.991 | 0.711 |
| D1 | 0.955, 1.000, 1.000, 1.000, 1.000 | 0.991 | 0.820 |
| D2 | 0.955, 1.000, 1.000, 1.000, 1.000 | 0.991 | 0.991 |

Synthetic door-shift table (held-out block current × [0.9, 0.95, 1.05, 1.1, 1.15, 1.2] and + [-50.0, 50.0, 100.0] mA; blocked-CV mean IoU-F1):

| Shift | D0 | D1 | D2 |
|---|---|---|---|
| 0.9 | 0.964 | 0.945 | 0.991 |
| 0.95 | 0.991 | 0.973 | 0.991 |
| 1.05 | 0.945 | 0.991 | 0.991 |
| 1.1 | 0.745 | 0.945 | 0.991 |
| 1.15 | 0.327 | 0.591 | 0.991 |
| 1.2 | 0.291 | 0.473 | 0.991 |
| -50mA | 0.982 | 0.964 | 0.982 |
| +50mA | 0.836 | 0.955 | 0.991 |
| +100mA | 0.273 | 0.282 | 0.991 |

Held-out block's motor current scaled/offset before feature extraction; a synthetic stand-in for a door with a different Normal current level. A ratio rule is invariant to scaling by construction; the additive offsets and the unshifted parity are the informative checks.

Segmenter: 110/110 training cycles, mean IoU 1.000; 38 cycles on Test.csv; test band gaps 0.
Direction inference accuracy vs labels: 1.000 (0 unresolved of 110).
Frozen absolute cutoffs (mA·s): Open 2003.6, Close 1768.0; pooled 1880.8 — used only as the fallback.
Frozen relative rule (D2): baseline = 25th percentile of the recording's own per-direction integrals (≥ 8 cycles, plausibility [0.8, 1.25]× training Normal median); cutoff ratios Open 1.0986 (Normal ≤ 1.0333×, Abnormal ≥ 1.1681×), Close 1.1290 (Normal ≤ 1.1072×, Abnormal ≥ 1.1512×).
Nearest counterexamples: Open: highest Normal 1880.8, lowest Abnormal 2126.3; Close: highest Normal 1733.6, lowest Abnormal 1802.5

Selection rule: D2 (stream-relative) is selected if its unshifted blocked-CV mean is within 0.01 of D0 and its mean over the synthetic multiplicative shifts [0.9, 0.95, 1.05, 1.1, 1.15, 1.2] exceeds D0's by at least 0.05 (pre-registered, docs/EXPERIMENTS.md E1); otherwise the highest unshifted mean, ties to the simpler D0.

## Known limitations

- All 110 cycles appear to come from one door; no door/car identity exists in the data, so cross-door generalisation is untested on real data — the shift robustness table uses synthetic current scaling of the same door.
- Blocked-CV folds share the same door and session; scores are optimistic for a different door.
- Class ranges are disjoint within direction in training; a wide margin does not prove transfer.
- D2 needs at least 8 cycles per direction with a plausible baseline; otherwise it falls back to the absolute cutoff and flags the stream.

## Environment

- python: 3.13.6
- numpy: 2.5.3
- pandas: 3.0.6
- scipy: 1.18.1
- scikit-learn: 1.9.1
- platform: macOS-27.0-arm64-arm-64bit-Mach-O
