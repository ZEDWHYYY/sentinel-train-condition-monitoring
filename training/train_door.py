"""Door: segmenter assertion, direction accuracy, blocked-CV comparison of
D0 (absolute direction-conditioned integral rule), D1 (logistic) and D2 (the
same rule relative to the analysed recording's own per-direction baseline),
synthetic door-shift robustness (docs/EXPERIMENTS.md E1), artifact freeze."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from _paths import DATA, fingerprint, now
from diagnostics import door
from diagnostics.metrics import door_iou_f1

GAP_S = 1.0
BAND = (0.03, 10.0)
N_BLOCKS = 5
# D2 (pre-registered in docs/EXPERIMENTS.md, E1): baseline percentile, minimum cycles per direction, and the
# plausibility window of baseline / training-Normal-median outside which the absolute cutoff is used.
BASELINE_Q = 25
MIN_CYCLES = 8
PLAUSIBLE = (0.8, 1.25)
SHIFTS = [0.90, 0.95, 1.05, 1.10, 1.15, 1.20]      # multiplicative current shifts (synthetic "different door")
OFFSETS_MA = [-50.0, 50.0, 100.0]                  # additive current offsets


def load():
    d = door.parse(DATA / "Door" / "Train.csv")
    lab = pd.read_csv(DATA / "Door" / "Train_Segments_Answer.csv", dtype=str)
    lab["t0"], _ = door.parse_timestamps(lab["start_time"])
    lab["t1"], _ = door.parse_timestamps(lab["end_time"])
    return d, lab


def cycles_table(d, segs, position_sign):
    rows = []
    for a, b in segs:
        cyc = d.frame.iloc[a:b + 1]
        f = door.cycle_features(cyc, d.t[a:b + 1])
        direction, votes = door.infer_direction(cyc, position_sign)
        rows.append({**f, "t0": d.t[a], "t1": d.t[b], "a": a, "b": b, "direction": direction})
    return pd.DataFrame(rows)


def fit_rule(tab: pd.DataFrame) -> dict:
    cut, ranges, counts = {}, {}, {}
    for op in ("Open", "Close"):
        s = tab[tab.operation == op]
        n = s[s.status == "Normal"].current_integral_mAs
        a = s[s.status == "Abnormal resistance"].current_integral_mAs
        ranges[op] = {"Normal": [float(n.min()), float(n.max())],
                      "Abnormal resistance": [float(a.min()), float(a.max())]}
        counts[op] = {"Normal": int(len(n)), "Abnormal resistance": int(len(a))}
        if n.max() < a.min():
            cut[op] = float((n.max() + a.min()) / 2)
        else:  # overlapping: best balanced accuracy over candidate cuts
            cands = np.sort(np.r_[n.to_numpy(), a.to_numpy()])
            best = max(cands, key=lambda c: ((n <= c).mean() + (a > c).mean()))
            cut[op] = float(best)
    n_all = tab[tab.status == "Normal"].current_integral_mAs
    a_all = tab[tab.status != "Normal"].current_integral_mAs
    cands = np.sort(np.r_[n_all.to_numpy(), a_all.to_numpy()])
    pooled = float(max(cands, key=lambda c: ((n_all <= c).mean() + (a_all > c).mean())))
    return {"cutoffs": cut, "class_ranges": ranges, "class_counts": counts, "pooled_cutoff": pooled}


def fit_relative(tab: pd.DataFrame) -> dict:
    """D2 ratios per direction: baseline = BASELINE_Q-th percentile of that direction's integrals on the
    training stream; cutoff ratio = geometric midpoint of the highest Normal and lowest Abnormal ratios."""
    dirs = {}
    for op in ("Open", "Close"):
        s = tab[tab.operation == op]
        b = float(np.percentile(s.current_integral_mAs, BASELINE_Q))
        rn = float((s[s.status == "Normal"].current_integral_mAs / b).max())
        ra = float((s[s.status == "Abnormal resistance"].current_integral_mAs / b).min())
        dirs[op] = {"ratio_cutoff": float(np.sqrt(rn * ra)) if rn < ra else ra, "normal_ratio_max": rn, "abnormal_ratio_min": ra,
                    "train_baseline": b, "normal_median": float(s[s.status == "Normal"].current_integral_mAs.median())}
    return {"baseline_percentile": BASELINE_Q, "min_cycles_per_direction": MIN_CYCLES, "plausibility_window": list(PLAUSIBLE),
            "directions": dirs}


def pos_sign_from(tab: pd.DataFrame, d) -> dict:
    """Position-trend sign per direction, learned from the given (training-fold) cycles only."""
    signs = {"Open": [], "Close": []}
    for _, r in tab.iterrows():
        p = d.frame[door.POSITION].to_numpy()[int(r.a):int(r.b) + 1]
        signs[r.operation].append(np.sign(p[-1] - p[0]))
    return {op: int(np.sign(np.sum(v))) for op, v in signs.items()}


LOGIT_FEATS = ["current_integral_mAs", "mean_current_mA", "p90_current_mA", "duration_s"]


def fit_logit(tab: pd.DataFrame):
    X = tab[LOGIT_FEATS].to_numpy()
    X = np.c_[X, (tab.operation == "Open").to_numpy(float)]
    y = (tab.status != "Normal").astype(int).to_numpy()
    m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000))
    m.fit(X, y)
    return m


def run():
    d, lab = load()
    seg = door.segment(d.t, GAP_S, BAND)
    segs = seg["segments"]
    # --- segmenter assertion (build failure on regression)
    assert len(segs) == len(lab) == 110, f"segmenter produced {len(segs)} segments, expected 110"
    from diagnostics.metrics import interval_iou
    ious = [interval_iou(d.t[a], d.t[b], r.t0, r.t1) for (a, b), (_, r) in zip(segs, lab.iterrows())]
    assert min(ious) == 1.0, f"segmenter IoU regression: min {min(ious)}"
    test = door.parse(DATA / "Door" / "Test.csv")
    tseg = door.segment(test.t, GAP_S, BAND)

    # position trend sign learned from training labels (orientation is undocumented); the final bundle uses all
    # cycles, the CV folds below re-learn it from the training blocks only
    pos_sign = {"Open": 1, "Close": -1}
    tab = cycles_table(d, segs, pos_sign)
    tab["operation"] = lab.operation.to_numpy()
    tab["status"] = lab.status.to_numpy()
    pos_sign = pos_sign_from(tab, d)
    tab = cycles_table(d, segs, pos_sign)
    tab["operation"] = lab.operation.to_numpy()
    tab["status"] = lab.status.to_numpy()
    dir_acc = float((tab.direction == tab.operation).mean())
    dir_unresolved = int(tab.direction.isna().sum())
    test_tab = cycles_table(test, tseg["segments"], pos_sign)

    # --- blocked CV on contiguous blocks of the continuous stream, plus synthetic door shifts of the held-out block
    blocks = np.array_split(np.arange(len(tab)), N_BLOCKS)
    shift_keys = ["1.0"] + [str(x) for x in SHIFTS] + [f"{o:+g}mA" for o in OFFSETS_MA]
    fold_scores = {n: {k: [] for k in shift_keys} for n in ("D0", "D1", "D2")}
    oof = {"D0": [None] * len(tab), "D1": [None] * len(tab), "D2": [None] * len(tab)}
    fallbacks = 0
    for k, idx in enumerate(blocks):
        train_idx = np.setdiff1d(np.arange(len(tab)), idx)
        tr = tab.iloc[train_idx]
        fold_sign = pos_sign_from(tr, d)
        rule = fit_rule(tr)
        rel = fit_relative(tr)
        logit = fit_logit(tr)
        a0, b1 = tab.a.iloc[idx[0]], tab.b.iloc[idx[-1]]
        sub_t = d.t[a0:b1 + 1]
        s2 = door.segment(sub_t, GAP_S, BAND)
        truth = [(r.t0, r.t1, r.status) for _, r in lab.iloc[idx].iterrows()]
        for key in shift_keys:
            frame = d.frame.iloc[a0:b1 + 1].reset_index(drop=True).copy()
            if key.endswith("mA"):
                frame[door.CURRENT] = frame[door.CURRENT] + float(key[:-2])
            else:
                frame[door.CURRENT] = frame[door.CURRENT] * float(key)
            cyc = []
            for a, b in s2["segments"]:
                c = frame.iloc[a:b + 1]
                f = door.cycle_features(c, sub_t[a:b + 1])
                direction, _ = door.infer_direction(c, fold_sign)
                cyc.append((sub_t[a], sub_t[b], f, direction))
            baselines = door.stream_baselines([(f, dr) for _, _, f, dr in cyc], {**rule, "relative_rule": rel})
            for name in ("D0", "D1", "D2"):
                preds = []
                for j, (t0, t1, f, direction) in enumerate(cyc):
                    if name == "D0":
                        label, _, _ = door.classify(f, direction, {**rule})
                    elif name == "D2":
                        label, reasons, _ = door.classify(f, direction, {**rule, "relative_rule": rel}, baselines)
                        fallbacks += any(r.code == "baseline_unavailable" for r in reasons) and key == "1.0"
                    else:
                        x = np.r_[[f[c] for c in LOGIT_FEATS], float(direction == "Open")][None, :]
                        label = door.LABELS[int(logit.predict(x)[0])]
                    preds.append((t0, t1, label))
                    if key == "1.0" and j < len(idx):
                        oof[name][idx[j]] = label
                fold_scores[name][key].append(door_iou_f1(truth, preds)["score"])
    res = {}
    for n, by_key in fold_scores.items():
        s = by_key["1.0"]
        res[n] = {"fold_scores": s, "mean": float(np.mean(s)), "min": float(np.min(s)),
                  "shift_mean": {kk: float(np.mean(v)) for kk, v in by_key.items() if kk != "1.0"},
                  "shift_mean_multiplicative": float(np.mean([np.mean(by_key[str(x)]) for x in SHIFTS]))}
        y = tab.status.to_numpy()
        p = np.array(oof[n])
        res[n]["confusion"] = {t: {q: int(((y == t) & (p == q)).sum()) for q in door.LABELS} for t in door.LABELS}
    # selection (pre-registered, docs/EXPERIMENTS.md E1): D2 if it matches D0 unshifted (within 0.01) and beats it by >= 0.05
    # averaged over the multiplicative shifts; otherwise the highest unshifted mean, ties to the simpler D0.
    d2_ok = res["D2"]["mean"] >= res["D0"]["mean"] - 0.01 and res["D2"]["shift_mean_multiplicative"] >= res["D0"]["shift_mean_multiplicative"] + 0.05
    if d2_ok:
        selected = "D2"
    else:
        selected = "D0" if res["D0"]["mean"] >= res["D1"]["mean"] - 1e-9 else "D1"

    final = fit_rule(tab)
    # margins and sensitivity of the official metric to moving the cutoff
    sens = {}
    for op in ("Open", "Close"):
        rng = final["class_ranges"][op]
        grid = np.linspace(rng["Normal"][0], rng["Abnormal resistance"][1], 41)
        s = tab[tab.operation == op]
        truth = [(r.t0, r.t1, r.status) for _, r in s.iterrows()]
        vals = []
        for c in grid:
            preds = [(r.t0, r.t1, "Abnormal resistance" if r.current_integral_mAs > c else "Normal") for _, r in s.iterrows()]
            vals.append({"cutoff": float(c), "score": door_iou_f1(truth, preds)["score"]})
        sens[op] = {"margin_low": rng["Normal"][1], "margin_high": rng["Abnormal resistance"][0],
                    "nearest_normal": rng["Normal"][1], "nearest_abnormal": rng["Abnormal resistance"][0],
                    "curve": vals}

    # Normal reference envelopes per direction (aligned at movement start)
    reference = {}
    for op in ("Open", "Close"):
        s = tab[(tab.operation == op) & (tab.status == "Normal")]
        L = int(s.rows.max())
        M = np.full((len(s), L), np.nan)
        for i, (_, r) in enumerate(s.iterrows()):
            c = d.frame[door.CURRENT].to_numpy()[int(r.a):int(r.b) + 1]
            M[i, :len(c)] = c
        reference[op] = {"step_s": 0.02, "n": int(len(s)),
                         "p10": np.nanpercentile(M, 10, axis=0).round(2).tolist(),
                         "p50": np.nanpercentile(M, 50, axis=0).round(2).tolist(),
                         "p90": np.nanpercentile(M, 90, axis=0).round(2).tolist()}
    travel_min = float(0.8 * tab.position_travel.min())
    relative = fit_relative(tab)

    test_dirs = test_tab.direction.value_counts(dropna=False).to_dict()
    validation = {
        "task": "door", "created": now(), "metric": "IoU-weighted F1 (official)",
        "protocol": f"{N_BLOCKS} contiguous blocks of the continuous Train stream; for each block, rules fitted on the other blocks "
                    "and the full segmenter + direction + classifier pipeline run on the held-out block's rows.",
        "segmentation": {"segments": len(segs), "expected": 110, "mean_iou": float(np.mean(ious)),
                         "min_iou": float(np.min(ious)), "test_segments": len(tseg["segments"]),
                         "train_gap_histogram": seg["gap_histogram"], "test_gap_histogram": tseg["gap_histogram"],
                         "train_min_between_gap_s": seg["min_between_gap_s"], "test_min_between_gap_s": tseg["min_between_gap_s"],
                         "train_max_within_gap_s": seg["max_within_gap_s"], "test_band_gaps": len(tseg["band_gaps"])},
        "direction": {"accuracy_vs_labels": dir_acc, "unresolved": dir_unresolved, "n": len(tab),
                      "test_counts": {str(k): int(v) for k, v in test_dirs.items()}},
        "candidates": res, "selected": selected,
        "selection_rule": "D2 (stream-relative) is selected if its unshifted blocked-CV mean is within 0.01 of D0 and its mean over the "
                          f"synthetic multiplicative shifts {SHIFTS} exceeds D0's by at least 0.05 (pre-registered, docs/EXPERIMENTS.md E1); "
                          "otherwise the highest unshifted mean, ties to the simpler D0.",
        "shift_robustness": {"multiplicative_shifts": SHIFTS, "additive_offsets_mA": OFFSETS_MA,
                             "note": "Held-out block's motor current scaled/offset before feature extraction; a synthetic stand-in for a door "
                                     "with a different Normal current level. A ratio rule is invariant to scaling by construction; the additive "
                                     "offsets and the unshifted parity are the informative checks.",
                             "d2_fallbacks_unshifted": int(fallbacks)},
        "cutoff_sensitivity": sens,
        "limitations": [
            "All 110 cycles appear to come from one door; no door/car identity exists in the data, so cross-door generalisation is untested "
            "on real data — the shift robustness table uses synthetic current scaling of the same door.",
            "Blocked-CV folds share the same door and session; scores are optimistic for a different door.",
            "Class ranges are disjoint within direction in training; a wide margin does not prove transfer.",
            "D2 needs at least 8 cycles per direction with a plausible baseline; otherwise it falls back to the absolute cutoff and flags the stream.",
        ],
    }
    model = {
        "task": "door", "version": {"D0": "door-D0-1.0.0", "D1": "door-D1-1.0.0", "D2": "door-D2-1.1.0"}[selected],
        "method": selected,
        "method_name": ("Gap segmentation + direction-conditioned current-integral rule relative to the recording's own baseline"
                        if selected == "D2" else "Gap segmentation + direction-conditioned current-integral rule"),
        "created": now(), "training_fingerprint": fingerprint([DATA / "Door" / "Train.csv", DATA / "Door" / "Train_Segments_Answer.csv"]),
        "segmentation": {"gap_threshold_s": GAP_S, "review_band_s": list(BAND),
                         "justification": "Train in-cycle spacing 0.02 s; between-cycle gaps >= 10.21 s; no gaps in between."},
        "position_sign": pos_sign, "position_travel_min": travel_min,
        **final, "reference": reference,
        **({"relative_rule": relative} if selected == "D2" else {}),
        "labels": list(door.LABELS),
        "feature_schema": ["current_integral_mAs"],
        "estimators": {},
        "validation_summary": {"blocked_cv_mean": res[selected]["mean"], "direction_accuracy": dir_acc,
                               "shift_mean_multiplicative": res[selected]["shift_mean_multiplicative"]},
        "limitations": validation["limitations"],
    }
    return model, validation
