"""E3 (docs/EXPERIMENTS.md): bounded Rail stage-1 alternatives on the same hash-grouped folds and seeds.
R2a HistGradientBoosting stage 1 (+ ET side model); R2b direct 3-class Random Forest on all features."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

import _exp  # noqa: F401
import train_rail as tr
from _paths import DATA, now
from diagnostics.common import save_json
from diagnostics.metrics import rail_macro_f1

CURRENT = {"speed_matched": 0.7926012600307704, "full_set": 0.8099882016383075, "std": 0.017, "side_I_f1_sm_seed0": 0.6667}


def hgb(seed):
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, class_weight="balanced", random_state=seed)


def direct_rf_cv(df, y, subset=None, seeds=tr.SEEDS):
    idx = np.arange(len(df)) if subset is None else np.flatnonzero(subset)
    d = df.iloc[idx].reset_index(drop=True)
    yy = y[idx]
    cols = tr.stage1_cols(d) + tr.stage2_cols(d)
    X = d[cols].to_numpy()
    groups = d["sha"].to_numpy()
    scores, first = [], None
    for s in seeds:
        pred = np.empty(len(d), dtype=object)
        for a, b in tr.folds(tr.N_FOLDS, s).split(X, yy, groups):
            m = RandomForestClassifier(n_estimators=500, max_depth=8, min_samples_leaf=2, class_weight="balanced",
                                       random_state=s, n_jobs=-1).fit(X[a], yy[a])
            pred[b] = m.predict(X[b])
        scores.append(rail_macro_f1(list(yy), list(pred))["macro_f1"])
        first = first if first is not None else rail_macro_f1(list(yy), list(pred))
    return {"macro_f1_mean": float(np.mean(scores)), "macro_f1_by_seed": [float(x) for x in scores],
            "macro_f1_std": float(np.std(scores)), "seed0_detail": first, "n": int(len(d))}


def run():
    df, _ = tr.load("Train")
    lab = pd.read_csv(DATA / "Rail_Corrugation" / "Train_Labels.csv").set_index("filename").label
    y = lab.loc[df.file].to_numpy()
    matched = (y != "Normal") | (df.transitions.to_numpy() >= tr.SPEED_MATCH_MIN)
    tr.STAGE1["HGB"] = hgb
    exps = {}
    exps["R2a_HGB_sidemodel"] = {"full_set": tr.pipeline_cv(df, y, use_speed=False, stage1="HGB", side_mode="model"),
                                 "speed_matched": tr.pipeline_cv(df, y, subset=matched, use_speed=False, stage1="HGB", side_mode="model")}
    exps["R2b_direct_RF_3class"] = {"full_set": direct_rf_cv(df, y), "speed_matched": direct_rf_cv(df, y, subset=matched)}
    verdict = {}
    for k, e in exps.items():
        sm, fs = e["speed_matched"], e["full_set"]
        side1 = sm["seed0_detail"]["per_class"]["Side I"]["f1"]
        ok = sm["macro_f1_mean"] >= CURRENT["speed_matched"] + CURRENT["std"] and fs["macro_f1_mean"] >= 0.805 and side1 >= CURRENT["side_I_f1_sm_seed0"]
        verdict[k] = {"speed_matched": sm["macro_f1_mean"], "full_set": fs["macro_f1_mean"], "side_I_f1_sm_seed0": side1, "promote": bool(ok)}
        print(f"{k}: speed-matched {sm['macro_f1_mean']:.3f} ± {sm['macro_f1_std']:.3f}, full {fs['macro_f1_mean']:.3f} ± {fs['macro_f1_std']:.3f}, Side I F1 {side1:.3f} -> promote {ok}")
    for e in exps.values():
        for part in e.values():
            part.pop("seed0_errors", None)
    out = {"experiment": "E3_rail_stage1_alternatives", "created": now(), "current": CURRENT, "experiments": exps, "verdict": verdict,
           "promotion_rule": "speed-matched >= 0.793 + 0.017 AND full >= 0.805 AND Side I F1 (speed-matched, seed 0) >= 0.667"}
    save_json(_exp.OUT / "e3_rail_stage1.json", out)
    return out


if __name__ == "__main__":
    run()
