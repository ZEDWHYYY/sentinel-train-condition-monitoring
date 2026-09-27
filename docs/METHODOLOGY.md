# SENTINEL PS3 — methodology and validation

This document covers all four PS3 subsystems (Door, ACV, Rail Corrugation, SHM) in one document. The pre-registered model experiments are in [EXPERIMENTS](EXPERIMENTS.md).

SENTINEL is a local diagnostic web app for the four subsystems. A user uploads an official-format recording. The app validates it, applies a frozen, validated pipeline and shows the model's prediction in the official format with a download button. It then adds the evidence behind that prediction and a suggested inspection action. Nothing is trained on an uploaded file.

All figures below are **local development validation on the supplied training data**. They are not organizer scores and do not guarantee held-out performance. Numbers come from `reports/validation/*.json`, produced by `training/train_all.py`.

| Subsystem | Deployed method | Official metric | Local validation |
|---|---|---|---|
| Door | Gap segmentation + inferred direction + motor-current-integral rule **relative to the recording's own per-direction baseline** (D2) | IoU-weighted F1 | 0.991 (5 contiguous-block CV, full pipeline); 0.991 under synthetic door shifts vs 0.711 for the absolute rule |
| ACV | Peer cooling-residual ranking (A0), no fitted weights | Rank-decay | 0.979 (leave-one-case-out, 6 cases; 5 top-1, 1 rank 2) |
| Rail | Random Forest fault detection + Extra Trees side model on speed-free features | Macro F1 | 0.793 speed-matched (0.810 full set) |
| SHM | Gated rainflow power law, D = c·Σnᵢ·rangeᵢ^m, m fitted = 5.0 | max(0, 1−MAPE) | 0.975 (leave-one-file-out, 64 files) |

Local Overall = (0.991 + 0.979 + 0.793 + 0.975) / 4 = **0.934** (local validation only).

## Shared design

- **One pipeline everywhere.** `command-center/backend/diagnostics/` holds the parsers, features, frozen predictors, evidence builders and CSV serializers. Training (`training/`), the app worker and the CLI (`predict.py`) all import it. CLI output is tested byte-identical to app exports.
- **Frozen artifacts.** `artifacts/ps3/<task>/model.json` stores rules, thresholds, reference statistics, versions and training fingerprints. Rail's estimators are joblib files verified by SHA-256 before loading; uploads can never supply model objects.
- **Honest outputs.** Each finding carries a prediction, an evidence state (no trigger / review suggested), review reasons with a concrete next check, data-quality issues and a recording context (asset not linked, historical upload). The inspection advice is a separately versioned, derived view ([RECOMMENDATION_POLICY](RECOMMENDATION_POLICY.md)). It never changes a prediction or a CSV.

## Door

- **Segmentation.** Rows inside a cycle are 0.02 s apart; gaps between cycles are ≥ 10.2 s. Splitting on gaps > 1 s reproduces 110/110 training cycles at mean IoU 1.000 (asserted at build time) and finds 38 cycles in `Test.csv`. Any gap between 0.03 s and 10 s is flagged for review.
- **Direction.** Inferred per cycle from four cues — commands, motion flags, close switches, position trend. Accuracy on the 110 labelled cycles: 1.000, none unresolved. Unresolved direction routes to review and uses a pooled cutoff.
- **Classification (D2, stream-relative).** Motor-current integral per cycle. The Door Info Kit (§1.2) warns that "data distributions differ among doors; applying a uniform threshold leads to false alarms and missed detection", and the test stream showed exactly that: a tight Close cluster at 1751–1769 mA·s that the absolute cutoff (1768.0) split, and Open cycles above every training Normal. D2 therefore judges each cycle as a *ratio* to the recording's own per-direction baseline (the 25th percentile of that direction's integrals) against frozen ratio cutoffs learned on the training door (Open 1.0986×, Close 1.1290×, the geometric midpoints of the highest-Normal and lowest-Abnormal ratios). Fallbacks are frozen too: fewer than 8 cycles in a direction, or a baseline outside 0.8–1.25× the training Normal median, revert to the absolute cutoff and flag the stream (`baseline_unavailable`).
- **Validation and selection (pre-registered, [EXPERIMENTS](EXPERIMENTS.md) E1).** On the unshifted blocked CV D0, D1 and D2 tie at 0.991 (the same single miss in fold 1). To test transfer without a second door, the held-out block's motor current was scaled ×0.90–1.20 and offset ±50/+100 mA before feature extraction: D0 falls to 0.291 at ×1.2 and 0.273 at +100 mA, D1 to 0.47/0.28, D2 stays at 0.991 (0.982 at −50 mA). A ratio rule is invariant to scaling by construction, so the additive offsets and the unshifted parity are the informative checks. The promotion rule (D2 within 0.01 of D0 unshifted and ≥ 0.05 better over shifts) was written before the run and was met. Position sign and travel minimum are now fitted per fold.
- **Effect on Test.csv (inference only, no tuning).** 8 of 38 cycles are predicted Abnormal (D0: 10). The two that change are the 1769 mA·s Close cycle (now inside this door's Normal ratio range, 1.087×) and a 2010 mA·s Open cycle (1.081×, in the gap between the ratio ranges → Normal with a `near_boundary` flag). Review flags fall from 15 to 1 because the shifted clusters are Normal *relative to this door*. Whether that is right is unknown until the organizers score it; the pre-registered evidence says a ratio rule is the safer bet on a different door.

## ACV

- Header-driven parsing (`Car <NN> - <parameter>`), sheet chosen by header compatibility (the test sheet is `故障案例3-0620_20210624`), leading zeros preserved.
- The production contract uses indoor temperature, cooling target and running mode. Case 04's rich schema is mapped through recorded aliases (passenger-cabin temperature, target-temperature value); its cars 05–08 are empty. Cases 05/06 lack outdoor temperature, which is therefore not used.
- **Score (A0):** mean over valid, settled (≥ 10 min after entering) active-cooling samples of cabin temperature minus the median cabin temperature of the other cooling cars at the same time. No car ID, position or column order enters; a within-case permutation test passes.
- A1 (A0 plus a centred target residual) scored the same (0.979), so the preregistered tie rule kept A0.
- Review when the top-two margin is below 0.5 K (one sensor resolution step), when cars lack data (listed last in ID order, explicitly "not evidence of health"), when the leader changes on most days, or when the **hot-period leader** differs: the same peer residual restricted to the hottest third of the recording (a leak shows most under load) is reported as secondary evidence and raises `hot_period_disagreement` when it points to a different car.
- **Alternative rankers (pre-registered, [EXPERIMENTS](EXPERIMENTS.md) E2, leave-one-case-out).** Shortfall vs target 0.979 (5/6 top-1), full-demand share 0.625, cooling slope 0.604, z-mean of A0 and shortfall 0.979, **hot-period residual 1.000 (6/6)** but with a smaller normalised margin (0.340 vs A0's 0.358), so by the rule fixed in advance A0 stays the prediction and the hot-period result is shown as evidence. On the test case the two disagree (Car 03 overall, Car 04 in the hottest third, both ≈ +0.03 K), and the app states plainly that the top pick is uncertain (advice: *Watch*, compare Cars 03 and 04).

## Rail corrugation

- Channels are mapped by semantic header names (shuffled headers work), with the official order as a flagged fallback. Features per channel (full 10 kHz resolution): RMS, peak, kurtosis, crest factor, and Welch band energies over six bands from 20 Hz to 5 kHz. These are aggregated per side (median, max, Side I − Side II contrasts overall and per car).
- **Duplicate audit.** Two training files are byte-identical copies of two others (all four Normal). Cross-validation therefore uses stratified *group* folds keyed by file SHA-256, so identical files always share a fold, and the final model counts each duplicate once. Before this fix the headline was 0.805; the leak-free figure is 0.793.
- **Speed confound.** Fault files never have fewer than 654 pulse transitions, while 121/234 Normal files do. Speed features are excluded. Every configuration is scored with and without speed and on the speed-matched subset (101 Normal files ≥ 654 transitions + 38 faults). Adding speed does not help (0.791 vs 0.793 speed-matched), and no configuration collapses under speed matching.
- **Side-discrimination gate** (fixed before running: balanced accuracy ≥ 0.70 and above the 95th percentile of a label-permutation baseline, over the 38 fault files, 5 seeds × 5 grouped folds): Extra Trees on side-contrast features reached 0.879, so the gate **passed** and a side model is deployed. Simple Side I − Side II amplitude contrasts alone do not separate sides; higher-order and band contrasts do.
- Configurations (speed-matched macro F1): all-Normal 0.308; rule + majority side 0.424; ET + majority side 0.545; ET + contrast policy 0.634; ET + side model 0.740; **RF + side model 0.793**. The RF stage-1 challenger was added after a bounded stage-1 comparison on the same folds. These are therefore model-selection validation figures, not an untouched test.
- The out-of-fold misclassified files are listed in `reports/eda/rail.html` and `reports/validation/rail.json`.
- **Bounded alternatives (pre-registered, [EXPERIMENTS](EXPERIMENTS.md) E3, same folds and seeds).** HistGradientBoosting stage 1: 0.776 speed-matched / 0.788 full. Direct 3-class Random Forest on all features: 0.811 speed-matched / 0.803 full. The rule required ≥ 0.810 speed-matched *and* ≥ 0.805 full *and* no loss on Side I; the direct RF missed the full-set bar by 0.002, i.e. it is equivalent within seed noise (std 0.017), so the deployed model was kept rather than adding another selection round.
- Limitation: there is no acquisition/run provenance, so files from one run may share folds.

## SHM

- Headerless parsing keeps row 1. Reversals are taken after removing repeats, filtered by a hysteresis gate, and counted with three-point ASTM E1049 rainflow (verified on the ASTM worked example).
- Candidates (leave-one-file-out; gate and exponent chosen inside each fold): best constant 0.417; median constant 0.028; log-linear on range/RMS/cycles 0.787; Ridge on log cycle features 0.881; **power law 0.975** (MAPE 2.5%; low-target half 3.2%, high half 1.9%).
- Fitted exponent m = 5.0, against an exploratory peak-range estimate of 4.06. That early estimate's weak damage sums came from unpaired raw turning points; proper rainflow pairing resolves this. Gating changes nothing at m = 5 (gated = ungated 0.975); the gated definition is kept as the spec requires, and this is reported honestly rather than as "gated beats ungated".
- The constants are fitted to the dataset's labels. They are not calibrated material S–N constants. Review triggers: features outside the training range, and large disagreement with the log-linear challenger.

## Evaluation discipline

- Split protocols are fixed in code and saved with file hashes in `reports/validation/split_manifest.json`: contiguous Door blocks; whole-case ACV leave-one-out; stratified group Rail folds (group = file hash) over 5 seeds plus speed-matched evaluation; SHM leave-one-file-out. A duplicate audit found 2 identical Rail training files and no train/test duplicates.
- Preprocessing and thresholds are fitted inside folds. Organizer test files were processed only by the frozen method. Test.csv was inspected for compatibility, and that inspection led to a review note, not a threshold change.
- The dataset facts quoted above (row and cycle counts, class balance, the Rail speed confound, the SHM target range) are reproduced by `training/section0_facts.py`, with no divergences (`reports/section0_facts.json`).
- Every model change was pre-registered: the hypothesis and promotion rule were written before running ([EXPERIMENTS](EXPERIMENTS.md)), with scripts in `training/experiments/` and results in `reports/validation/experiments/`. One change was promoted (Door D2); two were not (ACV alternative rankers, Rail stage-1 alternatives) and are reported anyway.
- EDA reports: `reports/eda/index.html`. Evidence ledger: `reports/evidence_ledger.md`. Model cards: `artifacts/ps3/*/MODEL_CARD.md`.

## Assumptions where the documentation left a decision open

- **Validation splits (no official split is given).**
  - Door: contiguous time blocks of the single training stream, because neighbouring cycles are correlated and random splits would leak.
  - ACV: leave-one-case-out, because the cars within one case share a train and its operating conditions.
  - Rail: stratified folds grouped by file SHA-256, because two training files are byte-identical; repeated over five seeds.
  - SHM: leave-one-file-out, because file numbers are random and there is no chronology to block on.
- **Door output.** Each segment's start and end are the timestamps of its first and last samples, written back in the recording's own `Y-M-D-h-m-s-ms` format, which the Info Kit accepts. Open/Close is not required in the output, but it is inferred because the two directions draw different current.
- **ACV.** Cars are identified exactly as in each file's headers (`03`, not `3`). Outdoor temperature is not used, because cases 05 and 06 lack it. Case 04's rich schema is mapped through recorded column aliases. Cars without valid settled cooling data are ranked last in car-ID order, which is stated as *not* evidence that they are healthy.
- **Rail.** Axle-box positions 1, 3, 5 and 7 are Side I, and 2, 4, 6 and 8 are Side II (Info Kit §2.1). The speed pulse is counted, but no km/h figure is derived because the naive conversion gave implausible speeds. Speed features are excluded because of the confound described above.
- **SHM.** Stress units and sampling frequency are undocumented, so no physical S–N constants are assumed. The power-law constants are fitted to the damage labels.
- **All subsystems.** No model uses file names, file numbers or car IDs as features (tested). Organizer test inputs were only parsed for compatibility, never used to tune.

## From prediction to action

The interface translates model output into evidence an operator or engineer can inspect. The explanations and suggested checks do not change the model prediction or its CSV export.

**One results screen, read top to bottom.**

1. **Model prediction.** The official answer, in the official vocabulary:
   - Door: every detected open/close cycle with its start, end and `Normal` / `Abnormal resistance` label.
   - ACV: the most likely leaking car and the full ranking.
   - Rail: `Normal`, `Side I` or `Side II`, with counts and a per-file table for a batch.
   - SHM: the predicted damage.

   **Download prediction CSV** returns the exact `*_predictions.csv` for that analysis, written by the same serializer as `predictions.zip` and the CLI.
2. **Inspection advice.** A condition badge (Normal, Watch or Action required), shown in colour *and* text, with a one-sentence reason.
3. **Recommended action.** What to check, how urgently, and why. Each piece of evidence is listed with its measured value, unit, time or sample window and reference value, for example a Door cycle's motor-current integral against its cutoff. Each one links to the chart that shows it.
4. **Other likely actions.** Three alternatives, ranked by an evidence-support score from 0 to 1 whose formula can be expanded. The score is labelled as uncalibrated support, never as a probability.
5. **Supporting evidence.** Charts specific to each task, with zoom and hover, peak-preserving downsampling, declared units and text summaries:
   - Door: integral against cutoff per cycle, the cycle's current trace against the Normal 10–90th percentile band, and leaf position.
   - ACV: the leading car's temperature above its peers over time, and the score for every car.
   - Rail: vibration by car and side, the raw trace, and the spectrum against the Normal band.
   - SHM: the stress trace and the counted cycles.
6. **Data details.** Parsed rows and columns, the sampling rate and its source, data-quality issues and how they were treated, signal statistics, a parsed preview, model and policy versions, and the input SHA-256. A findings CSV is available for engineering records.

**Before analysis**, the upload screen parses the whole file and shows:

- the detected subsystem, which the user can change (the chosen parser must still accept the file);
- the row count and time coverage;
- any quality warnings.

Files that cannot be analysed are blocked, with a specific correction.

**For the new engineer**, the *Learn* page covers each subsystem:

- what the equipment does and what goes wrong;
- how SENTINEL decides;
- what normal looks like, with numbers read from the frozen models;
- how to read each chart;
- the maintenance decision a finding supports, with a technician's checklist and a glossary of the technical terms.

The *Methods* page shows every model against its baseline under the same folds, plus the split protocols and the forecasting decision.

**Uncertainty is shown, not hidden.**

- ACV: the top-two margin on the test case is 0.03 K, below one 0.5 K sensor step. The page says the top pick is uncertain while still exporting the full ranking, and it reports that the hot-period evidence (E2) points to a different car.
- Door: a cycle close to its cutoff is marked for review.
- Rail: a recording whose vibration is far above normal is flagged as a signal anomaly even when the corrugation label is Normal.

**Batch analysis and bundle.** *Past analyses → Analyse an official test batch* reads a complete provided test set in place (Rail's is 1.2 GB) and lists every prediction in one table. *Export prediction bundle* builds `predictions.zip` only from complete analyses whose inputs match the provided official test files by filename and SHA-256. Synthetic, training or modified files are rejected.

**What we deliberately did not build:** live status, failure dates or remaining life, probabilities without calibration, invented asset identity, work tracking or dispatch.

## Forecasting

Only ACV has contiguous telemetry. A leak-free cabin-temperature forecaster (Ridge on information available at the origin; leave-one-case-out; rolling origins) was compared with persistence at 10, 30 and 60 minutes. It made errors larger, not smaller (mean per-case change +9.0%, +3.6%, +2.6%) and improved on only 3–4 of the 6 held-out cases. By the rule fixed in advance it is not shipped. Details: `reports/forecasting_feasibility.md`.

## What SENTINEL does not claim

It gives no fleet health score, failure probability, remaining life, failure date, MTBF/MTTR or geographic defect location. Results describe historical recordings and do not certify fitness for service.
