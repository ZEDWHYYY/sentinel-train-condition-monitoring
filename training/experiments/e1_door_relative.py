"""E1 (docs/EXPERIMENTS.md): Door stream-relative cutoff D2 vs absolute D0 under synthetic door shifts.

Blocked CV on the 5 contiguous training blocks. The held-out block is re-segmented and, for D2,
its per-direction baseline is computed from the held-out block alone. Shifts multiply the held-out
block's motor current by s before feature extraction. No organizer test data is used.
"""
from __future__ import annotations

import numpy as np

import _exp  # noqa: F401
import train_door as td
from _paths import now
from diagnostics import door
from diagnostics.common import save_json
from diagnostics.metrics import door_iou_f1

SHIFTS = [0.90, 0.95, 1.05, 1.10, 1.15, 1.20]
OFFSETS_MA = [-50.0, 50.0, 100.0]  # additive offsets (mA) reported for honesty; not part of the promotion rule
Q = 25              # baseline percentile
MIN_CYCLES = 8      # per direction, else fall back to the absolute cutoff
PLAUSIBLE = (0.8, 1.25)  # baseline / training Normal median


def fit_relative(tab):
    out = {}
    for op in ("Open", "Close"):
        s = tab[tab.operation == op]
        b = float(np.percentile(s.current_integral_mAs, Q))
        rn = float((s[s.status == "Normal"].current_integral_mAs / b).max())
        ra = float((s[s.status != "Normal"].current_integral_mAs / b).min())
        r = float(np.sqrt(rn * ra)) if rn < ra else ra
        out[op] = {"ratio_cutoff": r, "normal_ratio_max": rn, "abnormal_ratio_min": ra, "train_baseline": b,
                   "normal_median": float(s[s.status == "Normal"].current_integral_mAs.median())}
    return out


def pos_sign_from(tab, lab_ops, d):
    signs = {"Open": [], "Close": []}
    for (_, r), op in zip(tab.iterrows(), lab_ops):
        p = d.frame[door.POSITION].to_numpy()[int(r.a):int(r.b) + 1]
        signs[op].append(np.sign(p[-1] - p[0]))
    return {op: int(np.sign(np.sum(v))) for op, v in signs.items()}


def run():
    d, lab = td.load()
    seg = door.segment(d.t, td.GAP_S, td.BAND)
    segs = seg["segments"]
    pos_all = {"Open": 1, "Close": -1}
    tab = td.cycles_table(d, segs, pos_all)
    tab["operation"] = lab.operation.to_numpy()
    tab["status"] = lab.status.to_numpy()
    blocks = np.array_split(np.arange(len(tab)), td.N_BLOCKS)
    res = {"D0": {}, "D2": {}}
    fallbacks = 0
    for shift in [1.0] + SHIFTS + [f"+{o:g}mA" if o > 0 else f"{o:g}mA" for o in OFFSETS_MA]:
        for name in res:
            res[name].setdefault(str(shift), [])
        for idx in blocks:
            tr_idx = np.setdiff1d(np.arange(len(tab)), idx)
            tr = tab.iloc[tr_idx]
            pos_sign = pos_sign_from(tr, tr.operation.tolist(), d)  # per fold (F4)
            rule = td.fit_rule(tr)
            rel = fit_relative(tr)
            a0, b1 = tab.a.iloc[idx[0]], tab.b.iloc[idx[-1]]
            frame = d.frame.iloc[a0:b1 + 1].reset_index(drop=True).copy()
            if isinstance(shift, str):
                frame[door.CURRENT] = frame[door.CURRENT] + float(shift.replace("mA", ""))
            else:
                frame[door.CURRENT] = frame[door.CURRENT] * shift
            sub_t = d.t[a0:b1 + 1]
            s2 = door.segment(sub_t, td.GAP_S, td.BAND)
            cyc = []
            for a, b in s2["segments"]:
                c = frame.iloc[a:b + 1]
                f = door.cycle_features(c, sub_t[a:b + 1])
                direction, _ = door.infer_direction(c, pos_sign)
                cyc.append((sub_t[a], sub_t[b], f, direction))
            truth = [(r.t0, r.t1, r.status) for _, r in lab.iloc[idx].iterrows()]
            # D0: absolute
            p0 = [(t0, t1, door.classify(f, dr, rule)[0]) for t0, t1, f, dr in cyc]
            res["D0"][str(shift)].append(door_iou_f1(truth, p0)["score"])
            # D2: relative to the held-out stream's own baseline
            base = {}
            for op in ("Open", "Close"):
                xs = [f["current_integral_mAs"] for _, _, f, dr in cyc if dr == op]
                if len(xs) >= MIN_CYCLES:
                    b = float(np.percentile(xs, Q))
                    lo, hi = PLAUSIBLE
                    if lo * rel[op]["normal_median"] <= b <= hi * rel[op]["normal_median"]:
                        base[op] = b
            p2 = []
            for t0, t1, f, dr in cyc:
                if dr in base:
                    label = "Abnormal resistance" if f["current_integral_mAs"] > base[dr] * rel[dr]["ratio_cutoff"] else "Normal"
                else:
                    fallbacks += 1
                    label = door.classify(f, dr, rule)[0]
                p2.append((t0, t1, label))
            res["D2"][str(shift)].append(door_iou_f1(truth, p2)["score"])
    summary = {n: {s: {"mean": float(np.mean(v)), "folds": [float(x) for x in v]} for s, v in r.items()} for n, r in res.items()}
    shift_mean = {n: float(np.mean([summary[n][str(s)]["mean"] for s in SHIFTS])) for n in res}
    promote = (summary["D2"]["1.0"]["mean"] >= summary["D0"]["1.0"]["mean"] - 0.01) and (shift_mean["D2"] >= shift_mean["D0"] + 0.05)
    final_rel = fit_relative(tab)
    offset_keys = [f"+{o:g}mA" if o > 0 else f"{o:g}mA" for o in OFFSETS_MA]
    out = {"experiment": "E1_door_relative_cutoff", "created": now(), "shifts": SHIFTS, "additive_offsets_mA": OFFSETS_MA,
           "by_offset": {n: {k: summary[n][k]["mean"] for k in offset_keys} for n in res}, "baseline_percentile": Q,
           "min_cycles_per_direction": MIN_CYCLES, "plausibility_window": PLAUSIBLE,
           "unshifted": {n: summary[n]["1.0"] for n in res}, "by_shift": summary, "shift_mean": shift_mean,
           "fallbacks_to_absolute": fallbacks, "final_relative_rule_all_training": final_rel,
           "promotion_rule": "D2 unshifted mean >= D0 - 0.01 AND mean over shifts >= D0 + 0.05", "promote_D2": bool(promote)}
    save_json(_exp.OUT / "e1_door_relative.json", out)
    print("unshifted", {n: round(summary[n]["1.0"]["mean"], 4) for n in res})
    for s in SHIFTS:
        print(f"shift {s}: D0 {summary['D0'][str(s)]['mean']:.3f}  D2 {summary['D2'][str(s)]['mean']:.3f}")
    for k in offset_keys:
        print(f"offset {k}: D0 {summary['D0'][k]['mean']:.3f}  D2 {summary['D2'][k]['mean']:.3f}")
    print("shift means", shift_mean, "fallbacks", fallbacks, "PROMOTE D2:", promote)
    print("final ratios", {k: round(v["ratio_cutoff"], 4) for k, v in final_rel.items()})
    return out


if __name__ == "__main__":
    run()
