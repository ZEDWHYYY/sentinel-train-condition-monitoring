# Evidence-ranked inspection policy

Version `engineering-evidence-1.0`. This derived policy does **not** modify frozen predictions or the official bundle CSVs. It is an uncalibrated inspection aid, not a safety release, fault-cause probability or repair-success predictor. No filenames, fixture labels or held-out labels enter a decision.

## What confidence means

The displayed value is a dimensionless **evidence support score, 0–1**. It describes the strength of the signal used to propose a check. Scores for different checks use different evidence and are not mutually exclusive probabilities. Ranking is descending score, with a stable ID tie-break. A primary action is selected by condition; an alternative can have a higher score because it addresses a narrower, better-supported check. Every action exposes its exact scoring basis, measured evidence, units, source window and chart anchor. No usable estimate means Unavailable and unscored checks (zero), not artificially different confidences.

The thresholds below are transparent engineering heuristics. Synthetic tests establish software behavior, **not clinical/safety-grade fault validation**. Calibration against independent inspection outcomes remains open.

## Door

Use the movement with the largest current integral / frozen cutoff. Action required: at least one abnormal movement and the largest ratio ≥1.15. Watch: any abnormal movement below that margin, review reason or quality warning. Otherwise Normal means all assessed movements are below their cutoffs, not a guarantee of safe operation.

Primary support = distance from cutoff / (distance + learned training boundary gap), multiplied by finite-current completeness. Alternatives: repeat-motion comparison `(abnormal+1)/(cycles+2)`; verify travel `training minimum/(training minimum+observed travel+1)`; current acquisition `(missing+1)/(rows+2)`. These are suggestions to inspect/compare, not diagnoses of obstruction, alignment or sensor failure.

## ACV

Use contemporaneous **settled, valid cooling** residuals. Action required: leading mean peer residual ≥1 K and top-two gap ≥0.5 K. Watch: residual ≥0.25 K, incomplete comparable-car coverage, model review reasons or acquisition warnings. In particular, a quiet but near-tied ranking must not produce confident Normal advice: no official healthy controls exist. Synthetic healthy controls can therefore show Watch (not a critical alert). Otherwise Normal means no material relative-temperature signal; a leak shared by all cars remains undetectable by a peer comparison.

Primary support: clear anomaly = smoothed share of samples above 1 K × gap/(gap+0.5 K); Watch = min(smoothed quiet share, |mean residual|/(|mean residual|+1 K)); Normal = smoothed share within ±1 K. Alternatives are the next three car-specific sensor/cooling comparisons: positive residual/(residual+1 K) × usable rows/(usable rows+120). Nonpositive peer residuals use their measured target offset/(offset+1 K)/sqrt(rows+1), explicitly a weak sensor/target check. Missing comparison coverage is an acquisition problem, not a leak claim. The 30 s exposure assumption and °C assumption are reported.

## Rail

The corrugation classifier is preserved. A synthetic strong oscillation was still classified Normal, showing that target-class detection does not cover all vibration anomalies. An independent amplitude check therefore compares the larger side-median RMS to the training Normal median, 0.211715 m/s². Action required: frozen corrugation fault **or** ratio ≥3. Watch: ratio ≥0.75 or model review reason. Otherwise Normal. The intentionally conservative 0.75 reference triggers comparison, not a fault declaration.

Primary support: detected fault = uncalibrated forest vote; broad vibration anomaly = ratio/(ratio+1); Normal = 1−vote. Alternatives: side contrast `|I−II|/(I+II)`; sensor/domain-shift check `|ratio−1|/(|ratio−1|+2)`; repeat pass ambiguity `1−|2×vote−1|`. A large amplitude with a Normal target label is explicitly called a **signal anomaly**, never confirmed corrugation. Location along the track is unknown.

## SHM

Only stress burden is supported; official recordings contain healthy operation, not fault labels. Action required: peak-to-peak range / maximum training range ≥1.5. This means verify calibration and inspect unusually high stress, **not structural failure**. Watch: estimated segment D ≥0.2 or review reasons; 0.2 is a workflow review reference, not a physical failure limit. Otherwise Normal is routine trend review, not a health certificate.

Primary support: high stress ratio/(ratio+1), Watch |ratio−1|/(|ratio−1|+1), routine 1/(1+ratio). Alternatives: largest counted range/(range+training maximum); contextual load check D/(D+1); acquisition continuity `(missing+1)/(input samples+2)`. D is dimensionless and fitted to organizer labels. Unknown stress units, sampling frequency, AW0/AW4 context and chronology prohibit a defensible remaining-life estimate.

## Guardrails and remaining limits

Broad numerical scale guards reject gross mismatches/outliers rather than convert units silently. They cannot reliably detect every plausible unit conversion. Required schemas, minimum sample counts and missing-current/channel coverage are checked before inference. Temporal duplicates/gaps are disclosed; original SHM indices are preserved for display. SHM cycle counting still joins finite observations, which can miss extrema across gaps and must be reviewed. Model artifacts remain fixed; advisory conditions may be more conservative than model labels. No synthetic benchmark establishes deployment accuracy.
