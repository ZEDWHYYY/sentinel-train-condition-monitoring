"""Rail: two-stage model with speed-confound ablation, speed-matched
evaluation and the side-discrimination gate."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import rail_features
from _paths import DATA, fingerprint, now
from diagnostics import rail
from diagnostics.metrics import RAIL_LABELS, rail_macro_f1

SEEDS = [0, 1, 2, 3, 4]
N_FOLDS = 5
SPEED_MATCH_MIN = 654
GATE_MIN_BALANCED_ACC = 0.70  # search budget and pass criterion fixed before running


def load(split="Train"):
    rows = rail_features.extract_all(split)
    feats = pd.DataFrame([rail.side_features(r["ch"]) for r in rows])
    feats["file"] = [r["file"] for r in rows]
    feats["transitions"] = [r["transitions"] for r in rows]
    feats["sha"] = [r["sha"] for r in rows]  # identical files share a CV group
    return feats, rows


def folds(n_splits, seed):
    return StratifiedGroupKFold(n_splits, shuffle=True, random_state=seed)


def stage1_cols(df):
    return [c for c in df.columns if c.endswith("_med_all") or c.endswith("_max_all")]


def stage2_cols(df):
    return [c for c in df.columns if "_contrast_" in c]


def et(seed):
    return ExtraTreesClassifier(n_estimators=300, max_depth=6, min_samples_leaf=2, class_weight="balanced",
                                max_features="sqrt", random_state=seed, n_jobs=-1)


def rf(seed):
    return RandomForestClassifier(n_estimators=500, max_depth=8, min_samples_leaf=2, class_weight="balanced",
                                  random_state=seed, n_jobs=-1)


STAGE1 = {"ET": et, "RF": rf}


def rule_fit(x, y):
    cands = np.unique(x)
    return float(max(cands, key=lambda c: ((x[y == 0] <= c).mean() + (x[y == 1] > c).mean())))


def side_gate(df, y):
    fault = y != "Normal"
    X2 = df.loc[fault, stage2_cols(df)].to_numpy()
    y2 = (y[fault] == "Side II").astype(int)
    g2 = df.loc[fault, "sha"].to_numpy()
    out = {}
    for name, mk in (("ExtraTrees", lambda s: et(s)),
                     ("Logistic", lambda s: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000)))):
        accs = []
        for s in SEEDS:
            p = np.zeros(len(y2), int)
            for tr, te in folds(N_FOLDS, s).split(X2, y2, g2):
                m = mk(s).fit(X2[tr], y2[tr])
                p[te] = m.predict(X2[te])
            accs.append(balanced_accuracy_score(y2, p))
        # permutation baseline: same protocol on shuffled side labels
        perm = []
        rng = np.random.default_rng(0)
        for k in range(20):
            yp = rng.permutation(y2)
            p = np.zeros(len(yp), int)
            for tr, te in folds(N_FOLDS, k).split(X2, yp, g2):
                p[te] = mk(k).fit(X2[tr], yp[tr]).predict(X2[te])
            perm.append(balanced_accuracy_score(yp, p))
        out[name] = {"balanced_accuracy_mean": float(np.mean(accs)), "balanced_accuracy_by_seed": [float(a) for a in accs],
                     "permutation_95th": float(np.percentile(perm, 95)), "permutation_mean": float(np.mean(perm))}
    best = max(out, key=lambda k: out[k]["balanced_accuracy_mean"])
    b = out[best]
    established = b["balanced_accuracy_mean"] >= GATE_MIN_BALANCED_ACC and b["balanced_accuracy_mean"] > b["permutation_95th"]
    # single-feature contrast policy (documented fallback candidate)
    c = "vib_log_rms_contrast_med"
    return {"families": out, "best": best, "established": bool(established),
            "criterion": f"mean balanced accuracy >= {GATE_MIN_BALANCED_ACC} over {len(SEEDS)} seeds of stratified group "
                         f"{N_FOLDS}-fold CV on the 38 fault files AND above the 95th percentile of a label-permutation baseline",
            "coin_flip": 0.5, "n": int(fault.sum()), "support": {"Side I": int((y2 == 0).sum()), "Side II": int((y2 == 1).sum())},
            "contrast_feature": c}


def pipeline_cv(df, y, *, use_speed: bool, stage1: str, side_mode: str, subset=None, seeds=SEEDS):
    """Out-of-fold full-pipeline macro F1. side_mode: 'model' | 'majority' | 'contrast'."""
    idx = np.arange(len(df)) if subset is None else np.flatnonzero(subset)
    d = df.iloc[idx].reset_index(drop=True)
    yy = y[idx]
    c1 = stage1_cols(d) + (["transitions"] if use_speed else [])
    X1 = d[c1].to_numpy()
    X2 = d[stage2_cols(d)].to_numpy()
    yb = (yy != "Normal").astype(int)
    scores, per_seed_preds = [], []
    groups = d["sha"].to_numpy()
    for s in seeds:
        pred = np.empty(len(d), dtype=object)
        for tr, te in folds(N_FOLDS, s).split(X1, yy, groups):
            if stage1 in STAGE1:
                m1 = STAGE1[stage1](s).fit(X1[tr], yb[tr])
                is_fault = m1.predict_proba(X1[te])[:, 1] >= 0.5
            else:
                col = c1.index("vib_log_rms_med_all")
                cut = rule_fit(X1[tr, col], yb[tr])
                is_fault = X1[te, col] > cut
            ftr = tr[yb[tr] == 1]
            y2tr = (yy[ftr] == "Side II").astype(int)
            if side_mode == "model":
                m2 = et(s).fit(X2[ftr], y2tr)
                side = np.where(m2.predict(X2[te]) == 1, "Side II", "Side I")
            elif side_mode == "majority":
                side = np.full(len(te), "Side II" if y2tr.mean() >= 0.5 else "Side I", dtype=object)
            else:
                col = stage2_cols(d).index("vib_log_rms_contrast_med")
                cut = rule_fit(-X2[ftr, col], y2tr)  # Side II has lower (more negative) contrast
                side = np.where(-X2[te, col] > cut, "Side II", "Side I")
            pred[te] = np.where(is_fault, side, "Normal")
        per_seed_preds.append(pred)
        scores.append(rail_macro_f1(list(yy), list(pred))["macro_f1"])
    detail = rail_macro_f1(list(yy), list(per_seed_preds[0]))
    return {"macro_f1_mean": float(np.mean(scores)), "macro_f1_by_seed": [float(x) for x in scores],
            "macro_f1_std": float(np.std(scores)), "seed0_detail": detail, "n": int(len(d)),
            "seed0_errors": [{"file": f, "truth": t, "predicted": p} for f, t, p in zip(d["file"], yy, per_seed_preds[0]) if t != p]}


def psd_reference(files, n=30):
    rng = np.random.default_rng(3)
    pick = rng.choice(files, size=min(n, len(files)), replace=False)
    out = {}
    acc = {"vibration": [], "shock": []}
    f = None
    for fn in pick:
        d = rail.parse(DATA / "Rail_Corrugation" / "Train" / fn)
        for kind in acc:
            for car in (1, 4, 8):
                for pos in range(1, 9):
                    f, p = rail.psd(d, car, pos, kind)
                    acc[kind].append(np.log10(p + 1e-12))
    for kind, arrs in acc.items():
        A = np.array(arrs)
        step = 2  # halve resolution for storage
        out[kind] = {"f": f[::step].tolist(), "p10": np.percentile(A, 10, axis=0)[::step].round(3).tolist(),
                     "p50": np.percentile(A, 50, axis=0)[::step].round(3).tolist(),
                     "p90": np.percentile(A, 90, axis=0)[::step].round(3).tolist(), "n": int(len(pick))}
    return out


def run():
    df, rows = load("Train")
    lab = pd.read_csv(DATA / "Rail_Corrugation" / "Train_Labels.csv").set_index("filename").label
    y = lab.loc[df.file].to_numpy()
    tr = df.transitions.to_numpy()
    matched = (y != "Normal") | (tr >= SPEED_MATCH_MIN)
    counts = {c: int((y == c).sum()) for c in RAIL_LABELS}

    gate = side_gate(df, y)
    exps = {}
    for name, kw in {
        "R0_rule_majority": dict(use_speed=False, stage1="rule", side_mode="majority"),
        "R1_ET_majority": dict(use_speed=False, stage1="ET", side_mode="majority"),
        "R1_ET_contrast": dict(use_speed=False, stage1="ET", side_mode="contrast"),
        "R1_ET_sidemodel": dict(use_speed=False, stage1="ET", side_mode="model"),
        "R1_ET_sidemodel_WITH_speed": dict(use_speed=True, stage1="ET", side_mode="model"),
        "R1b_RF_sidemodel": dict(use_speed=False, stage1="RF", side_mode="model"),
        "R1b_RF_sidemodel_WITH_speed": dict(use_speed=True, stage1="RF", side_mode="model"),
    }.items():
        full = pipeline_cv(df, y, **kw)
        sm = pipeline_cv(df, y, subset=matched, **kw)
        exps[name] = {"config": kw, "full_set": full, "speed_matched": sm}
    majority = {"macro_f1": rail_macro_f1(list(y), ["Normal"] * len(y))["macro_f1"]}

    # choose side policy: model only if the gate is established, else best deterministic policy
    eligible = [n for n, e in exps.items() if not e["config"]["use_speed"]
                and (gate["established"] or e["config"]["side_mode"] != "model")]
    selected_name = max(eligible, key=lambda n: exps[n]["speed_matched"]["macro_f1_mean"])
    side_choice = exps[selected_name]["config"]["side_mode"]
    stage1_choice = exps[selected_name]["config"]["stage1"]
    collapse = exps[selected_name]["speed_matched"]["macro_f1_mean"] < 0.5 * exps[selected_name]["full_set"]["macro_f1_mean"]

    # ---- final fit (speed-free) on all training files
    import joblib
    from _paths import ARTIFACT_DIR
    from diagnostics.common import sha256_file
    out_dir = ARTIFACT_DIR / "rail"
    out_dir.mkdir(parents=True, exist_ok=True)
    c1, c2 = stage1_cols(df), stage2_cols(df)
    first = ~df["sha"].duplicated().to_numpy()  # exact duplicate files counted once in the final fit
    n_dup = int((~first).sum())
    y_all, tr_all = y, tr
    df, y = df[first].reset_index(drop=True), y[first]
    rows = [r for r, keep in zip(rows, first) if keep]
    yb = (y != "Normal").astype(int)
    if stage1_choice not in STAGE1:
        raise SystemExit("Rule-only stage 1 selected; deployable bundle for it is not implemented.")
    m1 = STAGE1[stage1_choice](0).fit(df[c1].to_numpy(), yb)
    estimators = {}
    joblib.dump(m1, out_dir / "stage1.joblib")
    estimators["stage1"] = {"file": "stage1.joblib", "sha256": sha256_file(out_dir / "stage1.joblib"),
                            "type": type(m1).__name__, "classes": [0, 1]}
    fault = yb == 1
    y2 = (y[fault] == "Side II").astype(int)
    if side_choice == "model":
        m2 = et(0).fit(df.loc[fault, c2].to_numpy(), y2)
        joblib.dump(m2, out_dir / "stage2.joblib")
        estimators["stage2"] = {"file": "stage2.joblib", "sha256": sha256_file(out_dir / "stage2.joblib"),
                                "type": "ExtraTreesClassifier", "classes": [0, 1]}
        side_policy = {"established": True}
    elif side_choice == "contrast":
        cf = "vib_log_rms_contrast_med"
        cut = -rule_fit(-df.loc[fault, cf].to_numpy(), y2)
        side_policy = {"established": False, "feature": cf, "cutoff": cut, "if_greater": "Side I", "otherwise": "Side II",
                       "description": f"Deterministic policy: Side I if median Side I − Side II log-RMS contrast > {cut:.3f}, else Side II. "
                                      "Not a validated side diagnosis."}
    else:
        side_policy = {"established": False, "feature": "vib_log_rms_contrast_med", "cutoff": float("inf"),
                       "if_greater": "Side I", "otherwise": "Side II",
                       "description": "Deterministic policy: every detected fault is labelled Side II (the more frequent fault side in training). Not a validated side diagnosis."}
    ranges = {k: [float(df[k].min()), float(df[k].max())] for k in c1}
    normal_rms = float(np.median([np.median(10 ** r["ch"][:, :, 0, 0]) for r, yy in zip(rows, y) if yy == "Normal"]))
    test_df, _ = load("Test")
    test_tr = test_df.transitions.to_numpy()
    speed_inventory = {
        "train": {c: {"min": int(tr_all[y_all == c].min()), "median": float(np.median(tr_all[y_all == c])),
                      "max": int(tr_all[y_all == c].max()), "flat": int((tr_all[y_all == c] == 0).sum())} for c in RAIL_LABELS},
        "test": {"n": int(len(test_tr)), "min": int(test_tr.min()), "median": float(np.median(test_tr)), "max": int(test_tr.max()),
                 "flat": int((test_tr == 0).sum()), "below_600": int((test_tr < 600).sum())},
        "normal_at_or_above_654": int(((y_all == "Normal") & (tr_all >= SPEED_MATCH_MIN)).sum()),
        "decision": "Speed-derived features excluded from the deployed model (the default); the ablation is recorded.",
    }
    validation = {
        "task": "rail", "created": now(), "metric": "Macro F1 over Normal/Side I/Side II (official)",
        "protocol": f"Stratified group {N_FOLDS}-fold CV (group = file SHA-256, so byte-identical files share a fold) repeated over "
                    f"seeds {SEEDS}; out-of-fold full two-stage pipeline. No acquisition/run metadata exists, so grouping by run is not possible (disclosed).",
        "duplicates": {"exact_duplicate_training_files": n_dup,
                       "treatment": "grouped together in every CV split; counted once in the final fit"},
        "class_counts": counts, "majority_baseline": majority, "experiments": exps, "side_gate": gate,
        "selected": selected_name, "stage1": stage1_choice, "side_choice": side_choice,
        "selection_rule": "Highest speed-matched mean macro F1 among speed-free configurations; the side model is eligible only if the gate passed. "
                          "The RF stage-1 challenger was added after a bounded stage-1 comparison on the same folds, so these are "
                          "model-selection validation figures, not an untouched final test.",
        "speed_matched_collapse": bool(collapse), "speed_inventory": speed_inventory,
        "limitations": [
            "No acquisition/run provenance: files from the same run may share folds, which can inflate scores.",
            "Fault files were acquired at higher pulse rates than half of the Normal files (speed confound); "
            "the speed-matched figure is the honest headline.",
            "Side assignment " + ("passed the gate." if gate["established"] else "did not pass the gate; side labels follow a documented policy and every fault prediction is routed to review."),
            "The pulse-to-km/h conversion is unverified; no speed is shown to users.",
        ],
    }
    model = {
        "task": "rail", "version": f"rail-{selected_name}-1.0.0", "method": selected_name,
        "method_name": f"Two-stage: {type(m1).__name__} fault detection on side-aggregated features + " +
                       ("Extra Trees side model" if side_choice == "model" else "documented side policy"),
        "created": now(),
        "training_fingerprint": fingerprint([DATA / "Rail_Corrugation" / "Train_Labels.csv"]) + ":" + rail_features.FEATURE_VERSION,
        "feature_version": rail_features.FEATURE_VERSION,
        "stage1_features": c1, "stage2_features": c2, "stage1_threshold": 0.5,
        "review": {"stage1_band": [0.35, 0.65]}, "side_policy": side_policy,
        "estimators": estimators, "feature_ranges": ranges, "labels": list(RAIL_LABELS),
        "welch": rail.WELCH, "bands_hz": rail.BANDS, "uses_speed": False,
        "reference": {"normal_side_rms_median": normal_rms,
                      "psd": psd_reference(list(df.file[y == "Normal"]))},
        "validation_summary": {"full_set": exps[selected_name]["full_set"]["macro_f1_mean"],
                               "speed_matched": exps[selected_name]["speed_matched"]["macro_f1_mean"],
                               "side_gate_established": gate["established"]},
        "limitations": validation["limitations"],
    }
    return model, validation
