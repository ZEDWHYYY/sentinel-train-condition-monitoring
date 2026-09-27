"""ACV telemetry forecast feasibility evaluation.

Target: a car's cabin temperature h minutes ahead, from information available at
the forecast origin only (its recent cabin temperature, cooling target, running
mode, and the contemporaneous peer median). Evaluation: leave-one-case-out; within
the held-out case every sample is an origin (rolling). Baseline: persistence.

    python training/forecast_acv.py -> reports/validation/forecast_acv.json
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from _paths import DATA, REPORTS, now
from diagnostics import acv
from diagnostics.common import save_json

HORIZONS_MIN = [10, 30, 60]
STEP_S = 30
LAGS = [1, 2, 4, 10, 20]  # samples back (30 s each)


def case_frames():
    labels = pd.read_csv(DATA / "ACV" / "Train_Labels.csv", dtype=str)
    out = {}
    for fn in labels.filename:
        d = acv.parse(DATA / "ACV" / "Train" / fn)
        # regular 30 s grid only where the recording is contiguous; never bridge gaps
        t = d.time
        step = float(t.diff().dt.total_seconds().median())
        ok_grid = (t.diff().dt.total_seconds() == step) | (t.diff().isna())
        seg = (~ok_grid).cumsum()
        out[fn] = (d, seg.to_numpy(), step)
    return out


def design(d: acv.ACVData, seg: np.ndarray, step: float, hm: int):
    h = int(round(hm * 60 / step))
    lags = [max(1, int(round(k * STEP_S / step))) for k in LAGS]
    ind = d.signals["indoor"]
    tgt = d.signals["target"]
    cool = d.signals["mode"].isin(list(acv.COOLING_MODES)).fillna(False)
    X, y, persist = [], [], []
    for car in d.cars:
        s = ind[car].to_numpy(float)
        if np.isnan(s).all():
            continue
        peers = ind.drop(columns=car).median(axis=1).to_numpy(float)
        tg = tgt[car].to_numpy(float)
        c = cool[car].to_numpy(float)
        n = len(s)
        for i in range(max(lags), n - h):
            if seg[i + h] != seg[i] or seg[i - max(lags)] != seg[i]:
                continue  # origin and target must lie in the same contiguous block
            lagv = [s[i - k] for k in lags]
            row = [s[i], *(s[i] - v for v in lagv), peers[i] - s[i], tg[i] - s[i], c[i]]
            if not np.all(np.isfinite(row)) or not np.isfinite(s[i + h]):
                continue
            X.append(row)
            y.append(s[i + h] - s[i])  # predict the change
            persist.append(s[i])
    return np.asarray(X), np.asarray(y), np.asarray(persist)


def run():
    cases = case_frames()
    res = {}
    for hm in HORIZONS_MIN:
        mats = {fn: design(d, seg, step, hm) for fn, (d, seg, step) in cases.items()}
        mats = {fn: m for fn, m in mats.items() if len(m[0])}
        per_case = []
        for held in mats:
            Xtr = np.vstack([mats[f][0] for f in mats if f != held])
            ytr = np.concatenate([mats[f][1] for f in mats if f != held])
            Xte, yte, _ = mats[held]
            if len(Xte) == 0:
                continue
            m = Ridge(alpha=1.0).fit(Xtr, ytr)
            mae_model = float(np.mean(np.abs(m.predict(Xte) - yte)))
            mae_persist = float(np.mean(np.abs(yte)))  # persistence predicts zero change
            per_case.append({"case": held, "n_origins": int(len(yte)), "mae_ridge_K": mae_model,
                             "mae_persistence_K": mae_persist,
                             "step_s": cases[held][2],
                             "improvement": 1 - mae_model / mae_persist if mae_persist else 0.0})
        imp = [p["improvement"] for p in per_case]
        res[f"{hm}min"] = {"per_case": per_case, "mean_improvement": float(np.mean(imp)),
                           "cases_improved": int(sum(i > 0 for i in imp)), "n_cases": len(imp),
                           "mae_ridge_mean_K": float(np.mean([p["mae_ridge_K"] for p in per_case])),
                           "mae_persistence_mean_K": float(np.mean([p["mae_persistence_K"] for p in per_case]))}
    # promotion rule fixed in advance: >= 15% mean MAE reduction and better in >= 5 of 6 cases at 30 and 60 min
    promoted = all(res[k]["mean_improvement"] >= 0.15 and res[k]["cases_improved"] >= 5 for k in ("30min", "60min"))
    out = {"created": now(), "target": "cabin temperature change over horizon h (K)",
           "inputs_at_origin": "own cabin temperature and lagged changes, peer median minus own, cooling target minus own, cooling-mode flag",
           "protocol": "leave-one-case-out; rolling origins over every contiguous 30 s sample of the held-out case; no gap bridging",
           "baseline": "persistence (no change)", "horizons": res,
           "promotion_rule": ">= 15% mean MAE reduction vs persistence and improvement in >= 5 of 6 held-out cases at both 30 and 60 min",
           "promoted": bool(promoted)}
    save_json(REPORTS / "validation" / "forecast_acv.json", out)
    for k, v in res.items():
        print(k, f"ridge {v['mae_ridge_mean_K']:.3f} K vs persistence {v['mae_persistence_mean_K']:.3f} K,",
              f"improvement {v['mean_improvement']:+.1%}, cases improved {v['cases_improved']}/{v['n_cases']}")
    print("promoted:", promoted)
    return out


if __name__ == "__main__":
    run()
