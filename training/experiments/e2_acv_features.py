"""E2 (docs/EXPERIMENTS.md): physically motivated ACV rankers A2a-A2d and A3 vs A0, leave-one-case-out.
Fixed formulas, no fitted weights. No organizer test data is used for selection."""
from __future__ import annotations

import numpy as np
import pandas as pd

import _exp  # noqa: F401
import train_acv as ta
from _paths import now
from diagnostics import acv
from diagnostics.common import save_json
from diagnostics.metrics import acv_case_score

P = ta.PARAMS


def peer_res(frame, cars):
    out = pd.DataFrame(index=frame.index, columns=cars, dtype=float)
    for c in cars:
        others = frame.drop(columns=c)
        n = others.notna().sum(axis=1)
        out[c] = frame[c] - others.median(axis=1).where(n >= P["min_peers"])
    return out


def candidates(d: acv.ACVData) -> dict[str, dict[str, float | None]]:
    cars = d.cars
    cool = acv.cooling_mask(d, P["settle_rows"])
    ind = d.signals["indoor"].where(cool)
    tgt = d.signals["target"].where(cool)
    pr = peer_res(ind, cars)
    ok = {c: int(pr[c].notna().sum()) >= P["min_valid_rows"] for c in cars}
    a0 = {c: float(pr[c].mean()) if ok[c] else None for c in cars}
    sf = peer_res(ind - tgt, cars)
    a2a = {c: float(sf[c].mean()) if ok[c] and sf[c].notna().any() else None for c in cars}
    mode = d.signals["mode"]
    cool_any = mode.isin(list(acv.COOLING_MODES)).fillna(False)
    full = (mode == "Full Cooling").fillna(False) & cool_any
    share = {c: float(full[c].sum() / max(1, cool_any[c].sum())) for c in cars}
    a2b = {c: (share[c] - float(np.median([share[o] for o in cars if o != c]))) if ok[c] else None for c in cars}
    pm = d.signals["indoor"].median(axis=1)
    hot = pm >= pm.quantile(2 / 3)
    a2c = {c: float(pr.loc[hot, c].mean()) if ok[c] and pr.loc[hot, c].notna().sum() >= P["min_valid_rows"] // 3 else None for c in cars}
    slopes = {}
    for c in cars:
        cc = cool_any[c].to_numpy()
        x = d.signals["indoor"][c].to_numpy(float)
        starts = np.flatnonzero(np.diff(np.r_[0, cc.astype(int)]) == 1)
        vals = [(x[s:s + 21][-1] - x[s]) / 20 for s in starts if len(x[s:s + 21]) == 21 and np.isfinite(x[s:s + 21]).all()]
        slopes[c] = float(np.mean(vals)) if vals else np.nan
    a2d = {c: (slopes[c] - float(np.nanmedian([slopes[o] for o in cars if o != c]))) if ok[c] and np.isfinite(slopes[c]) else None for c in cars}
    def z(s):
        v = np.array([x for x in s.values() if x is not None], float)
        sd = v.std() if len(v) > 1 and v.std() > 0 else 1.0
        return {c: ((s[c] - v.mean()) / sd if s[c] is not None else None) for c in s}
    z0, za = z(a0), z(a2a)
    a3 = {c: ((z0[c] + za[c]) / 2 if z0[c] is not None and za[c] is not None else z0[c]) for c in cars}
    return {"A0": a0, "A2a_shortfall": a2a, "A2b_full_demand_share": a2b, "A2c_hot_period_residual": a2c,
            "A2d_cooling_slope": a2d, "A3_z_mean_A0_A2a": a3}


def run():
    cases = ta.load_cases()
    per = {}
    for name, (d, true_car) in cases.items():
        for k, scores in candidates(d).items():
            order = acv.rank(scores)
            vals = [v for v in scores.values() if v is not None]
            spread = (max(vals) - min(vals)) if len(vals) > 1 and max(vals) > min(vals) else None
            t = scores.get(true_car)
            runner = max([v for c, v in scores.items() if c != true_car and v is not None], default=None)
            margin = ((t - runner) / spread) if (t is not None and runner is not None and spread) else None
            per.setdefault(k, []).append({"case": name, "rank": order.index(true_car) + 1,
                                          "score": acv_case_score(order, true_car, len(order)),
                                          "normalised_margin": margin, "ranking": order})
    summary = {}
    for k, rows in per.items():
        summary[k] = {"mean": float(np.mean([r["score"] for r in rows])), "top1": int(sum(r["rank"] == 1 for r in rows)),
                      "mean_normalised_margin": float(np.mean([r["normalised_margin"] for r in rows if r["normalised_margin"] is not None])),
                      "per_case": rows}
    a0 = summary["A0"]
    promoted = [k for k, s in summary.items() if k != "A0" and s["mean"] > a0["mean"] + 1e-9 and s["mean_normalised_margin"] >= a0["mean_normalised_margin"]]
    out = {"experiment": "E2_acv_alternative_rankers", "created": now(), "protocol": "leave-one-case-out, fixed formulas",
           "candidates": summary, "promotion_rule": "LOO mean > A0 (6/6 top-1) AND mean normalised margin >= A0",
           "promoted": promoted}
    save_json(_exp.OUT / "e2_acv_features.json", out)
    for k, s in summary.items():
        print(f"{k:28s} mean {s['mean']:.3f} top1 {s['top1']}/6 margin {s['mean_normalised_margin']:+.3f} ranks {[r['rank'] for r in s['per_case']]}")
    print("PROMOTED:", promoted)
    return out


if __name__ == "__main__":
    run()
