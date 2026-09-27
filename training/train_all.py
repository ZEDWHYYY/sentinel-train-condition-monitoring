"""Train, validate and freeze all four PS3 task bundles.

    python training/train_all.py            # all tasks
    python training/train_all.py door shm   # selected tasks

Writes artifacts/ps3/<task>/model.json (+ estimator files), MODEL_CARD.md,
reports/validation/<task>.json and reports/validation/summary.json.
"""
from __future__ import annotations

import platform
import sys
import time

import numpy as np
import sklearn

from _paths import ARTIFACT_DIR, REPORTS, now
from diagnostics.common import load_json, save_json


def versions():
    import pandas, scipy
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pandas.__version__,
            "scipy": scipy.__version__, "scikit-learn": sklearn.__version__, "platform": platform.platform()}


def headline(task, v):
    """Selected model's local score plus the comparison rows shown on the Method page."""
    if task == "door":
        c = v["candidates"]
        rows = [{"name": "D0 absolute direction-conditioned integral rule", "score": c["D0"]["mean"], "selected": v["selected"] == "D0"},
                {"name": "D1 regularised logistic regression", "score": c["D1"]["mean"], "selected": v["selected"] == "D1"}]
        if "D2" in c:
            rows.append({"name": "D2 integral rule relative to the recording's own baseline", "score": c["D2"]["mean"], "selected": v["selected"] == "D2"})
        return {"metric": "IoU-weighted F1", "value": c[v["selected"]]["mean"], "scope": "5 contiguous-block CV, full pipeline",
                "shift_robustness": {k: c[k].get("shift_mean_multiplicative") for k in c if "shift_mean_multiplicative" in c[k]},
                "comparison": rows}
    if task == "acv":
        c = v["candidates"]
        return {"metric": "Rank-decay score", "value": c[v["selected"]]["mean"], "scope": "leave-one-case-out, 6 cases",
                "comparison": [{"name": "Random ranking (expected)", "score": 4.5 / 8, "selected": False},
                               {"name": "A0 peer cooling residual", "score": c["A0"]["mean"], "selected": v["selected"] == "A0"},
                               {"name": "A1 peer + target residual", "score": c["A1"]["mean"], "selected": v["selected"] == "A1"}]}
    if task == "rail":
        e = v["experiments"]
        names = {"R0_rule_majority": "R0 amplitude rule + majority side", "R1_ET_majority": "Extra Trees + majority side",
                 "R1_ET_contrast": "Extra Trees + contrast-rule side", "R1_ET_sidemodel": "Extra Trees + side model",
                 "R1b_RF_sidemodel": "Random Forest + side model"}
        return {"metric": "Macro F1", "value": e[v["selected"]]["speed_matched"]["macro_f1_mean"],
                "scope": "speed-matched grouped CV (headline)", "full_set": e[v["selected"]]["full_set"]["macro_f1_mean"],
                "comparison": [{"name": "All-Normal baseline", "score": v["majority_baseline"]["macro_f1"], "selected": False}] +
                              [{"name": n, "score": e[k]["speed_matched"]["macro_f1_mean"], "selected": v["selected"] == k}
                               for k, n in names.items()]}
    c = v["candidates"]
    names = {"S0_constant": "S0 best constant", "S1b_loglinear": "S1b log-linear (range, RMS, cycles)",
             "S2_ridge_log": "S2 Ridge on log cycle features", "S1_power_gated": "S1 gated rainflow power law"}
    return {"metric": "max(0, 1−MAPE)", "value": c[v["selected"]]["score"], "scope": "leave-one-file-out, 64 files",
            "comparison": [{"name": n, "score": c[k]["score"], "selected": v["selected"] == k} for k, n in names.items()]}


def model_card(task, m, v) -> str:
    h = headline(task, v)
    lines = [f"# Model card — {task.upper()}", "",
             f"- **Version:** `{m['version']}`", f"- **Method:** {m['method_name']} (`{m['method']}`)",
             f"- **Created:** {m['created']}", f"- **Training fingerprint:** `{m['training_fingerprint'][:16]}…`",
             f"- **Official metric:** {v['metric']}",
             f"- **Local validation ({h['scope']}):** {h['metric']} = {h['value']:.3f}"
             + (f" (full set {h['full_set']:.3f})" if "full_set" in h else ""), "",
             "These are local development-validation figures on the supplied training data. They are not organizer "
             "results and do not guarantee held-out performance.", "", "## Protocol", "", v["protocol"], "",
             "## Candidates compared", ""]
    if task == "door":
        lines += ["| Candidate | Fold scores | Mean | Mean under synthetic current shifts |", "|---|---|---|---|"]
        for k, c in v["candidates"].items():
            sm = c.get("shift_mean_multiplicative")
            lines.append(f"| {k} | {', '.join(f'{s:.3f}' for s in c['fold_scores'])} | {c['mean']:.3f} | {sm:.3f} |" if sm is not None
                         else f"| {k} | {', '.join(f'{s:.3f}' for s in c['fold_scores'])} | {c['mean']:.3f} | — |")
        if "shift_robustness" in v:
            sr = v["shift_robustness"]
            lines += ["", f"Synthetic door-shift table (held-out block current × {sr['multiplicative_shifts']} and + {sr['additive_offsets_mA']} mA; "
                          "blocked-CV mean IoU-F1):", "", "| Shift | " + " | ".join(v["candidates"]) + " |", "|---|" + "---|" * len(v["candidates"])]
            keys = list(next(iter(v["candidates"].values()))["shift_mean"])
            for key in keys:
                lines.append(f"| {key} | " + " | ".join(f"{v['candidates'][n]['shift_mean'][key]:.3f}" for n in v["candidates"]) + " |")
            lines.append("")
            lines.append(sr["note"])
        s = v["segmentation"]
        lines += ["", f"Segmenter: {s['segments']}/{s['expected']} training cycles, mean IoU {s['mean_iou']:.3f}; "
                  f"{s['test_segments']} cycles on Test.csv; test band gaps {s['test_band_gaps']}.",
                  f"Direction inference accuracy vs labels: {v['direction']['accuracy_vs_labels']:.3f} "
                  f"({v['direction']['unresolved']} unresolved of {v['direction']['n']}).",
                  f"Frozen absolute cutoffs (mA·s): {', '.join(f'{k} {c:.1f}' for k, c in m['cutoffs'].items())}; pooled {m['pooled_cutoff']:.1f}"
                  + (" — used only as the fallback." if "relative_rule" in m else "."),
                  ] + ([f"Frozen relative rule (D2): baseline = {m['relative_rule']['baseline_percentile']}th percentile of the recording's own "
                        f"per-direction integrals (≥ {m['relative_rule']['min_cycles_per_direction']} cycles, plausibility "
                        f"{m['relative_rule']['plausibility_window']}× training Normal median); cutoff ratios "
                        + ", ".join(f"{k} {r['ratio_cutoff']:.4f} (Normal ≤ {r['normal_ratio_max']:.4f}×, Abnormal ≥ {r['abnormal_ratio_min']:.4f}×)"
                                    for k, r in m["relative_rule"]["directions"].items()) + "."] if "relative_rule" in m else []) + [
                  "Nearest counterexamples: " + "; ".join(
                      f"{op}: highest Normal {r['Normal'][1]:.1f}, lowest Abnormal {r['Abnormal resistance'][0]:.1f}"
                      for op, r in m["class_ranges"].items())]
    elif task == "acv":
        lines += ["| Candidate | Per-case rank of true car | Mean score | Top-1 | Top-3 |", "|---|---|---|---|---|"]
        for k, c in v["candidates"].items():
            ranks = ", ".join(f"{p['case'].replace('.xlsx', '')}: {p['rank']}" for p in c["per_case"])
            lines.append(f"| {k} | {ranks} | {c['mean']:.3f} | {c['top1']}/6 | {c['top3']}/6 |")
        lines += ["", f"Score definition: {m['score_definition']}",
                  f"Permutation test (relabel cars within a case): {'passed' if v['permutation_invariance'] else 'FAILED'}.",
                  f"Held-out schema: sheet `{v['test_schema']['sheet']}`, {v['test_schema']['columns']} columns, cars {', '.join(v['test_schema']['cars'])}."]
    elif task == "rail":
        lines += ["| Configuration | Full-set macro F1 | Speed-matched macro F1 |", "|---|---|---|"]
        for k, e in v["experiments"].items():
            lines.append(f"| {k} | {e['full_set']['macro_f1_mean']:.3f} ± {e['full_set']['macro_f1_std']:.3f} | "
                         f"{e['speed_matched']['macro_f1_mean']:.3f} ± {e['speed_matched']['macro_f1_std']:.3f} |")
        g = v["side_gate"]
        lines += ["", f"Majority-class (all Normal) baseline macro F1: {v['majority_baseline']['macro_f1']:.3f}.",
                  f"Side-discrimination gate: **{'established' if g['established'] else 'not established'}** — "
                  + "; ".join(f"{k}: balanced accuracy {f['balanced_accuracy_mean']:.3f} (permutation 95th pct {f['permutation_95th']:.3f})"
                              for k, f in g["families"].items()) + f". Criterion: {g['criterion']}.",
                  f"Speed inventory: training fault files have ≥ {v['speed_inventory']['train']['Side I']['min']} transitions; "
                  f"test files median {v['speed_inventory']['test']['median']:.0f}, {v['speed_inventory']['test']['flat']} flat. "
                  + v["speed_inventory"]["decision"],
                  f"Speed-matched collapse: {'YES — not promotable' if v['speed_matched_collapse'] else 'no'}.",
                  "", "Confusion (seed 0, full set, rows = truth):", "",
                  "| truth \\ predicted | Normal | Side I | Side II |", "|---|---|---|---|"]
        conf = v["experiments"][v["selected"]]["full_set"]["seed0_detail"]["confusion"]
        for t, row in conf.items():
            lines.append(f"| {t} | {row['Normal']} | {row['Side I']} | {row['Side II']} |")
    else:
        lines += ["| Candidate | Score | MAPE | Low-half MAPE | High-half MAPE |", "|---|---|---|---|---|"]
        for k, c in v["candidates"].items():
            lines.append(f"| {k} | {c['score']:.3f} | {c['mape']:.3f} | {c['mape_low_half']:.3f} | {c['mape_high_half']:.3f} |")
        sp = v["final_params"]["selected"]
        lines += ["", f"Selected formula: {sp['formula']}; gate {sp['gate']}, "
                  + (f"fitted exponent m = {sp['m']:.2f} (exploratory peak-range prior: {v['exponent_prior']})." if 'm' in sp else ""),
                  f"Gating effect: gated {v['gating_effect']['gated_score']:.3f} vs ungated {v['gating_effect']['ungated_score']:.3f}. "
                  + v["gating_effect"]["note"]]
    lines += ["", f"Selection rule: {v.get('selection_rule', '')}", "", "## Known limitations", ""]
    lines += [f"- {x}" for x in v["limitations"]]
    lines += ["", "## Environment", ""] + [f"- {k}: {val}" for k, val in versions().items()]
    return "\n".join(lines) + "\n"


def main(tasks):
    import train_acv, train_door, train_rail, train_shm
    runners = {"door": train_door.run, "acv": train_acv.run, "rail": train_rail.run, "shm": train_shm.run}
    if tasks == ["--summary-only"]:
        from diagnostics.common import load_json as lj
        summary = lj(REPORTS / "validation" / "summary.json")
        for t in ("door", "acv", "rail", "shm"):
            v = lj(REPORTS / "validation" / f"{t}.json")
            summary["tasks"][t].update(headline(t, v))
        save_json(REPORTS / "validation" / "summary.json", summary)
        print("summary refreshed")
        return
    summary_path = REPORTS / "validation" / "summary.json"
    summary = load_json(summary_path) if summary_path.exists() else {"tasks": {}}
    for t in tasks:
        t0 = time.time()
        print(f"[{t}] training and validating ...", flush=True)
        model, val = runners[t]()
        model["library_versions"] = versions()
        model["seed"] = 0
        save_json(ARTIFACT_DIR / t / "model.json", model)
        save_json(REPORTS / "validation" / f"{t}.json", val)
        (ARTIFACT_DIR / t / "MODEL_CARD.md").write_text(model_card(t, model, val), encoding="utf-8")
        summary["tasks"][t] = {"version": model["version"], "method": model["method_name"], **headline(t, val),
                               "created": model["created"], "limitations": val["limitations"]}
        print(f"[{t}] {headline(t, val)}  ({time.time() - t0:.0f}s)", flush=True)
    vals = [summary["tasks"][t]["value"] for t in ("door", "acv", "rail", "shm") if t in summary["tasks"]]
    summary["overall_local"] = sum(vals) / 4
    summary["average_attempted"] = sum(vals) / len(vals) if vals else None
    summary["updated"] = now()
    summary["note"] = ("Local development-validation summary. Overall = (Door + ACV + Rail + SHM)/4 with unattempted tasks "
                       "counted as zero; Average = mean of attempted tasks. Not an organizer leaderboard.")
    save_json(summary_path, summary)
    print("overall (local):", round(summary["overall_local"], 3))


if __name__ == "__main__":
    main(sys.argv[1:] or ["door", "acv", "rail", "shm"])
