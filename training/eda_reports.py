"""Generate the development EDA HTML reports and the evidence ledger.

    python training/eda_reports.py  -> reports/eda/{index,door,acv,rail,shm}.html, reports/evidence_ledger.md

Self-contained offline HTML (inline SVG, no external assets). Uses the same
parsers/features as the app and the saved validation records.
"""
from __future__ import annotations

import html
import json
import math

import numpy as np
import pandas as pd

import rail_features
from _paths import DATA, REPORTS, now
from diagnostics import acv, door, rail, shm
from diagnostics.common import load_json

OUT = REPORTS / "eda"
COL = {"Normal": "#6b7280", "Abnormal resistance": "#b42318", "Side I": "#1f5fbf", "Side II": "#c2410c",
       "Open": "#1f5fbf", "Close": "#c2410c", "test (unlabelled)": "#9ca3af"}
e = lambda s: html.escape(str(s))  # noqa: E731


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{e(title)}</title><style>"
            "body{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1b1f24}"
            "table{border-collapse:collapse;font-size:14px;margin:8px 0}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left}"
            "h2{margin-top:28px;border-bottom:1px solid #d0d7de}.note{font-size:14px;color:#4b5563}.hyp{background:#fffbeb;border:1px solid #f3d27a;padding:8px;border-radius:6px}"
            ".fact{background:#eef4ff;border:1px solid #bfd3f5;padding:8px;border-radius:6px}svg{background:#fff;border:1px solid #e5e7eb}"
            f"</style></head><body><p class='note'><a href='index.html'>EDA index</a> · generated {e(now())} from local training data</p>{body}</body></html>")


def table(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0])
    return ("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{e(_f(r[c]))}</td>" for c in cols) + "</tr>" for r in rows) + "</table>")


def _f(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    return v


def nice_ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if span / (m * mag) <= n)
    start = math.ceil(lo / step) * step
    return [round(start + k * step, 10) for k in range(int((hi - start) / step) + 1)]


def colour(name: str) -> str:
    base = name.split(" (n=")[0]
    return COL.get(base) or next((c for key, c in sorted(COL.items(), key=lambda kv: -len(kv[0])) if key in base), "#374151")


def lines(series: list[tuple[str, list[float], list[float], str]], title: str, xl: str, yl: str, W=820, H=280) -> str:
    """Multi-line SVG; series = [(name, xs, ys, colour)]."""
    M = 56
    xs_all = [x for _, xs, _, _ in series for x in xs]
    ys_all = [y for _, _, ys, _ in series for y in ys if y is not None and np.isfinite(y)]
    x0, x1, y0, y1 = min(xs_all), max(xs_all), min(ys_all), max(ys_all)
    pad = (y1 - y0) * 0.06 or 1
    y0, y1 = y0 - pad, y1 + pad
    sx = lambda v: M + (v - x0) / ((x1 - x0) or 1) * (W - M - 16)  # noqa: E731
    sy = lambda v: H - 34 - (v - y0) / (y1 - y0) * (H - 50)  # noqa: E731
    p = [f"<svg width='{W}' height='{H}' role='img' aria-label='{e(title)}'>"]
    for t in nice_ticks(y0, y1, 5):
        p.append(f"<line x1='{M}' x2='{W - 16}' y1='{sy(t):.1f}' y2='{sy(t):.1f}' stroke='#eef0f3'/>"
                 f"<text x='{M - 4}' y='{sy(t) + 4:.1f}' font-size='11' text-anchor='end'>{t:g}</text>")
    for t in nice_ticks(x0, x1, 8):
        p.append(f"<text x='{sx(t):.1f}' y='{H - 18}' font-size='11' text-anchor='middle'>{t:g}</text>")
    for name, xs, ys, col in series:
        pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys) if y is not None and np.isfinite(y))
        p.append(f"<polyline fill='none' stroke='{col}' stroke-width='1.4' points='{pts}'/>")
    p.append(f"<text x='{(W + M) / 2}' y='{H - 2}' font-size='12' text-anchor='middle'>{e(xl)}</text>")
    p.append(f"<text x='12' y='{H / 2}' font-size='12' transform='rotate(-90 12 {H / 2})' text-anchor='middle'>{e(yl)}</text></svg>")
    legend = " · ".join(f"<span style='color:{c}'>■</span> {e(n)}" for n, _, _, c in series)
    return "".join(p) + f"<div class='note'>{e(title)} — {legend}</div>"


def strip(groups: dict[str, list[float]], title: str, unit: str, cut: dict[str, float] | None = None, log=False) -> str:
    W, H, L = 820, 44 * len(groups) + 50, 190
    vals = [v for g in groups.values() for v in g if v is not None and np.isfinite(v)]
    if log:
        vals = [math.log10(v) for v in vals if v > 0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    sx = lambda v: L + (v - lo) / (hi - lo) * (W - L - 20)  # noqa: E731
    parts = [f"<svg width='{W}' height='{H}' role='img' aria-label='{e(title)}'>"]
    rng = np.random.default_rng(0)
    for k, (name, g) in enumerate(groups.items()):
        y = 30 + k * 44
        color = colour(name)
        parts.append(f"<text x='4' y='{y + 4}' font-size='12'>{e(name)} (n={len(g)})</text>")
        for v in g:
            if v is None or not np.isfinite(v) or (log and v <= 0):
                continue
            vv = math.log10(v) if log else v
            parts.append(f"<circle cx='{sx(vv):.1f}' cy='{y + rng.uniform(-10, 10):.1f}' r='3' fill='{color}' fill-opacity='0.7'/>")
        if cut and name in cut:
            c = math.log10(cut[name]) if log else cut[name]
            parts.append(f"<line x1='{sx(c):.1f}' x2='{sx(c):.1f}' y1='{y - 16}' y2='{y + 16}' stroke='#111' stroke-dasharray='3 2'/>")
    for t in nice_ticks(lo, hi, 6):
        lab = f"{10 ** t:.3g}" if log else f"{t:g}"
        parts.append(f"<text x='{sx(t):.1f}' y='{H - 8}' font-size='11' text-anchor='middle'>{lab}</text>")
    parts.append(f"</svg><div class='note'>{e(title)} — x axis: {e(unit)}{' (log scale)' if log else ''}."
                 + (" Dashed line = frozen cutoff." if cut else "") + "</div>")
    return "".join(parts)


def scatter(xs, ys, title, xl, yl, colors=None, diag=False, logx=False, logy=False) -> str:
    W, H, M = 520, 360, 50
    X = np.log10(xs) if logx else np.asarray(xs, float)
    Y = np.log10(ys) if logy else np.asarray(ys, float)
    lo_x, hi_x, lo_y, hi_y = X.min(), X.max(), Y.min(), Y.max()
    if diag:
        lo_x = lo_y = min(lo_x, lo_y)
        hi_x = hi_y = max(hi_x, hi_y)
    sx = lambda v: M + (v - lo_x) / (hi_x - lo_x or 1) * (W - M - 10)  # noqa: E731
    sy = lambda v: H - M + 10 - (v - lo_y) / (hi_y - lo_y or 1) * (H - M - 10)  # noqa: E731
    p = [f"<svg width='{W}' height='{H + 10}' role='img' aria-label='{e(title)}'>"]
    if diag:
        p.append(f"<line x1='{sx(lo_x)}' y1='{sy(lo_y)}' x2='{sx(hi_x)}' y2='{sy(hi_y)}' stroke='#9ca3af' stroke-dasharray='4 3'/>")
    for i, (a, b) in enumerate(zip(X, Y)):
        p.append(f"<circle cx='{sx(a):.1f}' cy='{sy(b):.1f}' r='3.5' fill='{(colors or ['#1f5fbf'] * len(X))[i]}' fill-opacity='0.75'/>")
    p.append(f"<text x='{W / 2}' y='{H + 6}' font-size='12' text-anchor='middle'>{e(xl)}{' (log scale)' if logx else ''}</text>")
    p.append(f"<text x='12' y='{H / 2}' font-size='12' transform='rotate(-90 12 {H / 2})' text-anchor='middle'>{e(yl)}{' (log scale)' if logy else ''}</text>")
    for t in np.linspace(lo_x, hi_x, 5):
        p.append(f"<text x='{sx(t):.1f}' y='{H - M + 26}' font-size='10' text-anchor='middle'>{(10 ** t if logx else t):.3g}</text>")
    for t in np.linspace(lo_y, hi_y, 5):
        p.append(f"<text x='{M - 4}' y='{sy(t) + 3:.1f}' font-size='10' text-anchor='end'>{(10 ** t if logy else t):.3g}</text>")
    p.append(f"</svg><div class='note'>{e(title)}</div>")
    return "".join(p)


# ---------------------------------------------------------------- reports

def door_report(ledger):
    v = load_json(REPORTS / "validation" / "door.json")
    m = load_json(REPORTS.parent / "artifacts" / "ps3" / "door" / "model.json")
    d = door.parse(DATA / "Door" / "Train.csv")
    lab = pd.read_csv(DATA / "Door" / "Train_Segments_Answer.csv", dtype=str)
    segs = door.segment(d.t, 1.0, (0.03, 10.0))["segments"]
    feats = [door.cycle_features(d.frame.iloc[a:b + 1], d.t[a:b + 1]) for a, b in segs]
    f = pd.DataFrame(feats)
    f["op"], f["st"] = lab.operation.values, lab.status.values
    te = door.parse(DATA / "Door" / "Test.csv")
    tres = door.analyze(te, m)
    body = ["<h1>Door — development EDA</h1>",
            f"<div class='fact'><b>Inventory.</b> Train.csv {len(d.frame):,} rows × 17 columns; Test.csv {len(te.frame):,} rows. "
            f"Labels: {int((lab.status == 'Normal').sum())} Normal, {int((lab.status != 'Normal').sum())} Abnormal resistance; "
            f"{int((lab.operation == 'Open').sum())} Open / {int((lab.operation == 'Close').sum())} Close. No door/car identity columns exist.</div>",
            "<h2>Segmentation</h2>", table([{"stream": "train", **{f"gaps {a}–{b} s": c for a, b, c in zip(v['segmentation']['train_gap_histogram']['edges_s'][:-1], v['segmentation']['train_gap_histogram']['edges_s'][1:], v['segmentation']['train_gap_histogram']['counts'])}},
                                            {"stream": "test", **{f"gaps {a}–{b} s": c for a, b, c in zip(v['segmentation']['test_gap_histogram']['edges_s'][:-1], v['segmentation']['test_gap_histogram']['edges_s'][1:], v['segmentation']['test_gap_histogram']['counts'])}}]),
            f"<p>Gap rule (&gt; 1 s) reproduces {v['segmentation']['segments']}/110 training cycles at mean IoU {v['segmentation']['mean_iou']:.3f}; "
            f"{v['segmentation']['test_segments']} cycles on Test.csv; no gaps in the 0.03–10 s band in either stream.</p>",
            "<h2>Which cycle features separate the classes</h2>"]
    for feat, unit in (("current_integral_mAs", "mA·s"), ("duration_s", "s"), ("peak_current_mA", "mA")):
        groups = {f"{op} / {st}": f[(f.op == op) & (f.st == st)][feat].tolist() for op in ("Open", "Close") for st in ("Normal", "Abnormal resistance")}
        cut = {f"{op} / {st}": m["cutoffs"][op] for op in ("Open", "Close") for st in ("Normal", "Abnormal resistance")} if feat == "current_integral_mAs" else None
        body.append(strip(groups, f"{feat} by direction and label", unit, cut))
    tg = {}
    for it in tres["items"]:
        tg.setdefault(f"test (unlabelled) {it['operation']}", []).append(it["features"]["current_integral_mAs"])
    test_cuts = {k: (tres["items"][0]["decision"]["cutoff"] if False else next(
        (it["decision"]["cutoff"] for it in tres["items"] if it["operation"] == k.split()[-1]), m["cutoffs"][k.split()[-1]])) for k in tg}
    body.append(strip(tg, "Test.csv current integral by inferred direction (unlabelled; inspected for compatibility, not used for tuning)", "mA·s", test_cuts))
    if "relative_rule" in m:
        rr = m["relative_rule"]["directions"]
        body.append("<div class='hyp'><b>Observation on Test.csv (not a tuning input).</b> Many unlabelled test cycles sit just above the highest "
                    "training Normal integral in each direction, and one Close cluster (1751–1769 mA·s) straddled the old absolute cutoff (1768.0). "
                    "This is consistent with a different door. The deployed D2 rule judges each cycle relative to the recording's own per-direction "
                    f"baseline (25th percentile) with frozen ratio cutoffs (Open {rr['Open']['ratio_cutoff']:.4f}×, Close {rr['Close']['ratio_cutoff']:.4f}×); "
                    "the dashed lines above are the cutoffs that resulted for this stream. D2 was promoted by a pre-registered synthetic-shift test on "
                    "training data (docs/EXPERIMENTS.md E1), not by inspecting these values.</div>")
    else:
        body.append("<div class='hyp'><b>Observation on Test.csv (not a tuning input).</b> Many unlabelled test cycles sit just above the highest "
                    "training Normal integral in each direction, and one Close cluster straddles the frozen cutoff. This is consistent with a different "
                    "door or condition. The frozen cutoff was not moved; affected cycles are routed to review.</div>")
    body.append("<h2>Example traces: Normal vs Abnormal resistance</h2>")
    cur = d.frame[door.CURRENT].to_numpy()
    for op in ("Open", "Close"):
        ser = []
        for st, col in (("Normal", "#6b7280"), ("Abnormal resistance", "#b42318")):
            idx = f.index[(f.op == op) & (f.st == st)]
            med = f.loc[idx, "current_integral_mAs"].median()
            k = int((f.loc[idx, "current_integral_mAs"] - med).abs().idxmin())
            a, b = segs[k]
            ser.append((f"{st} ({lab.segment_id.iloc[k]}, {f.current_integral_mAs.iloc[k]:.0f} mA·s)",
                        list(np.arange(b - a + 1) * 0.02), cur[a:b + 1].tolist(), col))
        body.append(lines(ser, f"{op}: motor current of the median-integral Normal and Abnormal training cycle", "seconds since cycle start", "mA"))
    body.append("<p class='note'>Abnormal resistance shows as sustained extra motor current over the movement, not a single spike — "
                "which is why the integral separates the classes while peak current does not.</p>")
    body.append("<h2>Candidate rules (blocked CV, full pipeline)</h2>")
    body.append(table([{"candidate": k, "fold scores": ", ".join(f"{s:.3f}" for s in c["fold_scores"]), "mean": c["mean"],
                        "Normal→Normal": c["confusion"]["Normal"]["Normal"],
                        "Normal→Abnormal": c["confusion"]["Normal"]["Abnormal resistance"],
                        "Abnormal→Normal": c["confusion"]["Abnormal resistance"]["Normal"],
                        "Abnormal→Abnormal": c["confusion"]["Abnormal resistance"]["Abnormal resistance"]}
                       for k, c in v["candidates"].items()]))
    body.append(f"<p>Direction inference: accuracy {v['direction']['accuracy_vs_labels']:.3f} on 110 labelled cycles, "
                f"{v['direction']['unresolved']} unresolved. Selected: {v['selected']} ({e(v['selection_rule'])}).</p>")
    if "shift_robustness" in v:
        keys = list(next(iter(v["candidates"].values()))["shift_mean"])
        body.append("<h2>Synthetic door shift (held-out block current scaled / offset)</h2>")
        body.append(table([{"shift": k, **{n: c["shift_mean"][k] for n, c in v["candidates"].items()}} for k in keys]))
        body.append("<p class='note'>" + e(v["shift_robustness"]["note"]) + "</p>")
    body.append("<h2>Failure cases</h2><p>One Abnormal cycle was called Normal in blocked-CV fold 1, where the fold-local cutoff was fitted without that "
                "fold's lowest Abnormal cycles. No cycle is misclassified by the final rule in-sample (not a held-out claim).</p>")
    body.append("<h2>Conclusion</h2><ul><li><b>Finding:</b> the gap rule segments training exactly; direction-conditioned current integral separates "
                "training classes with a wide margin.</li><li><b>Hypothesis:</b> the <i>ratio</i> to a door's own baseline transfers across doors — supported "
                "only by synthetic shifts of the single training door, so it remains a hypothesis until a second door is scored.</li></ul>")
    (OUT / "door.html").write_text(page("Door EDA", "".join(body)), encoding="utf-8")
    for op in ("Open", "Close"):
        r = m["class_ranges"][op]
        rel = m.get("relative_rule", {}).get("directions", {}).get(op)
        ledger.append({"id": f"DOOR-{op.upper()}-INTEGRAL", "formula": "Σ current·Δt over cycle" + (" ÷ stream p25 baseline" if rel else ""), "units": "ratio" if rel else "mA·s",
                       "condition": f"{op} movements", "direction/cutoff": (f"> {rel['ratio_cutoff']:.4f}× baseline ⇒ Abnormal (absolute fallback > {m['cutoffs'][op]:.1f})" if rel
                                                                             else f"> {m['cutoffs'][op]:.1f} ⇒ Abnormal"),
                       "selection partition": "all 110 training cycles (geometric midpoint of class-ratio gap)" if rel else "all 110 training cycles (midpoint of class gap)",
                       "evaluation partition": "5 contiguous blocks (fold-refitted)", "n": m["class_counts"][op],
                       "violations": f"nearest Normal {r['Normal'][1]:.1f}, nearest Abnormal {r['Abnormal resistance'][0]:.1f}; 1 CV miss",
                       "metric effect": f"blocked-CV IoU-F1 {v['candidates']['D0']['mean']:.3f}"})


def _acv_example() -> str:
    d = acv.parse(DATA / "ACV" / "Train" / "acv_case_06.xlsx")
    cool = acv.cooling_mask(d, 20)
    ind = d.signals["indoor"].where(cool)
    hours = ((d.time - d.time.iloc[0]).dt.total_seconds() / 3600).to_numpy()
    hr = np.floor(hours)
    peer = ind.drop(columns="06").median(axis=1)
    df = pd.DataFrame({"h": hr, "car06": ind["06"], "peers": peer}).groupby("h").mean()
    return lines([("Car 06 (the leaking car)", df.index.tolist(), df.car06.tolist(), "#b42318"),
                  ("median of the other cooling cars", df.index.tolist(), df.peers.tolist(), "#6b7280")],
                 "Hourly mean cabin temperature during settled active cooling, case 06", "hours since start", "°C")


def _forecast_section() -> str:
    p = REPORTS / "validation" / "forecast_acv.json"
    if not p.exists():
        return ""
    f = load_json(p)
    rows = [{"horizon": h, "Ridge MAE (K)": v["mae_ridge_mean_K"], "persistence MAE (K)": v["mae_persistence_mean_K"],
             "mean improvement": f"{v['mean_improvement']:+.1%}", "held-out cases improved": f"{v['cases_improved']}/{v['n_cases']}"}
            for h, v in f["horizons"].items()]
    return ("<h2>Forecasting evaluation (telemetry, not failure)</h2>"
            f"<p>{e(f['protocol'])}. Inputs at origin: {e(f['inputs_at_origin'])}.</p>" + table(rows) +
            f"<div class='hyp'><b>Decision: {'promoted' if f['promoted'] else 'not promoted'}.</b> Rule fixed in advance: "
            f"{e(f['promotion_rule'])}. Cabin temperature is not forecast better than by persistence, so no forecast is shipped.</div>")


def acv_report(ledger):
    v = load_json(REPORTS / "validation" / "acv.json")
    rows = []
    body = ["<h1>ACV — development EDA</h1>"]
    for fn in sorted((DATA / "ACV" / "Train").glob("*.xlsx")) + [DATA / "ACV" / "Test" / "acv_test_case.xlsx"]:
        d = acv.parse(fn)
        modes = pd.Series(d.signals["mode"].to_numpy().ravel()).value_counts().head(4).to_dict()
        rows.append({"file": fn.name, "sheet": d.sheet, "rows": len(d.time), "columns": d.n_columns,
                     "cars with data": sum(not d.signals["indoor"][c].isna().all() for c in d.cars),
                     "outdoor temp": "outdoor" in d.signals, "aliases": ", ".join(sorted({x for m in d.mapping.values() for x in m.values()} - {n[0] for n in acv.SIGNALS.values()}))[:80],
                     "top modes": json.dumps(modes, ensure_ascii=False)})
    body += ["<h2>Inventory and schema</h2>", table(rows),
             "<div class='fact'>Cases 05 and 06 lack outdoor temperature (so it is not used as a feature). "
             "Case 04 uses a rich schema; indoor/target come from recorded aliases and cars 05–08 are empty.</div>",
             "<h2>Leave-one-case-out ranking</h2>"]
    for k, c in v["candidates"].items():
        body.append(f"<h3>{e(k)} — mean {c['mean']:.3f}, top-1 {c['top1']}/6</h3><p class='note'>{e(v['definitions'][k])}</p>")
        body.append(table([{"case": p["case"], "true car": p["true_car"], "rank": p["rank"], "score": p["score"],
                            "margin top1−top2 (K)": p["margin_K"], "ranking": " ".join(p["ranking"]), "review": ", ".join(p["review"])} for p in c["per_case"]]))
    body += [f"<p>Permutation test (relabel cars within a case): {'passed' if v['permutation_invariance'] else 'FAILED'}. "
             "Car number, position and column order are not features.</p>",
             "<h2>Example: leaking car vs its peers (case 06)</h2>",
             _acv_example(),
             "<h2>Failure case</h2><p>Case 04: the true car (01) ranks second behind car 04; only four cars have data in that workbook.</p>",
             _forecast_section(),
             "<h2>Conclusion</h2><ul><li><b>Finding:</b> a leaking car runs warmer than its contemporaneous cooling peers.</li>"
             "<li><b>Hypothesis:</b> six cases cannot establish ranking generalisation; tie margins below one 0.5 K sensor step are routed to review.</li></ul>"]
    (OUT / "acv.html").write_text(page("ACV EDA", "".join(body)), encoding="utf-8")
    ledger.append({"id": "ACV-PEER-RESIDUAL", "formula": "mean(indoor − median indoor of other cooling cars) over settled valid cooling",
                   "units": "K", "condition": "active cooling modes, ≥10 min after entry, ≥3 peers", "direction/cutoff": "rank descending; review if top-2 margin < 0.5 K",
                   "selection partition": "preregistered, no fitted weights", "evaluation partition": "leave-one-case-out (6)", "n": 6,
                   "violations": "case 04 true car ranked 2", "metric effect": f"rank-decay {v['candidates'][v['selected']]['mean']:.3f}"})


def _rail_bands(rows, y) -> str:
    bands = [f"{a}-{b}" for a, b in rail.BANDS]
    ser = []
    for cls, col in (("Normal", "#6b7280"), ("Side I", "#1f5fbf"), ("Side II", "#c2410c")):
        chs = np.array([r["ch"] for r, yy in zip(rows, y) if yy == cls])  # files, car, pos, kind, feat
        for side, pos, dash in (("Side I", [0, 2, 4, 6], ""), ("Side II", [1, 3, 5, 7], " (Side II positions)")):
            if side == "Side II" and cls == "Normal":
                continue
            prof = np.median(chs[:, :, pos, 0, 4:], axis=(0, 1, 2))
            ser.append((f"{cls} files, {side} axle boxes", list(range(len(bands))), prof.tolist(), col if side == "Side I" else col + "99"))
    out = lines(ser, "Median log10 band energy of axle-box vibration (bands: " + ", ".join(bands) + " Hz)", "band index (0 = 20–100 Hz … 5 = 2–5 kHz)", "log10 energy")
    return out + ("<p class='note'>Fault files carry more energy in every band on both sides; the affected side is separated by "
                  "combinations of band, kurtosis and crest-factor contrasts (see the side-discrimination gate).</p>")


def rail_report(ledger):
    v = load_json(REPORTS / "validation" / "rail.json")
    rows = rail_features.extract_all("Train")
    lab = pd.read_csv(DATA / "Rail_Corrugation" / "Train_Labels.csv").set_index("filename").label
    y = [lab[r["file"]] for r in rows]
    tr = [r["transitions"] for r in rows]
    feats = pd.DataFrame([rail.side_features(r["ch"]) for r in rows])
    body = ["<h1>Rail corrugation — development EDA</h1>",
            f"<div class='fact'>272 training files (10,000 × 129 each): {y.count('Normal')} Normal, {y.count('Side I')} Side I, {y.count('Side II')} Side II. "
            "Test: 68 files. Features are cached per file hash; the corpus is never copied.</div>",
            "<h2>Speed pulse is an acquisition confound</h2>",
            strip({c: [t for t, yy in zip(tr, y) if yy == c] for c in ("Normal", "Side I", "Side II")}, "Pulse transitions per 1-s file", "transitions",
                  {c: 654 for c in ("Normal", "Side I", "Side II")}),
            "<p>Test speed inventory: " + ", ".join(f"{k.replace('_', ' ')} {val}" for k, val in v['speed_inventory']['test'].items())
            + ". Speed-derived features are excluded from the deployed model; the with/without-speed ablation is in the table below.</p>",
            f"<div class='fact'><b>Duplicate audit.</b> {v.get('duplicates', {}).get('exact_duplicate_training_files', 0)} training files are "
            "byte-identical copies of other training files (all Normal). They are kept in the same fold in every split and counted once in the "
            "final fit. No test file duplicates a training file.</div>",
            "<h2>Spectral profile by class and side</h2>",
            _rail_bands(rows, y),
            "<h2>Amplitude and side contrast</h2>",
            strip({c: [10 ** x for x, yy in zip(feats['vib_log_rms_med_all'], y) if yy == c] for c in ("Normal", "Side I", "Side II")},
                  "Median axle-box vibration RMS (both sides)", "m/s²", log=True),
            strip({c: [x for x, yy in zip(feats['vib_log_rms_contrast_med'], y) if yy == c] for c in ("Normal", "Side I", "Side II")},
                  "Side I − Side II log10 RMS contrast (median positions)", "log10 ratio"),
            strip({c: [x for x, yy in zip(feats['vib_kurtosis_contrast_med'], y) if yy == c] for c in ("Normal", "Side I", "Side II")},
                  "Side I − Side II kurtosis contrast", "kurtosis difference"),
            "<h2>Experiments (identical folds)</h2>",
            table([{"configuration": k, "full-set macro F1": x["full_set"]["macro_f1_mean"], "± sd": x["full_set"]["macro_f1_std"],
                    "speed-matched macro F1": x["speed_matched"]["macro_f1_mean"], "n matched": x["speed_matched"]["n"]} for k, x in v["experiments"].items()]),
            f"<p>Majority-class baseline macro F1: {v['majority_baseline']['macro_f1']:.3f}. Selected: {e(v['selected'])}. {e(v['selection_rule'])}</p>",
            "<h2>Side-discrimination gate</h2>",
            table([{"family": k, **{kk: vv for kk, vv in f.items() if kk != 'balanced_accuracy_by_seed'}} for k, f in v["side_gate"]["families"].items()]),
            f"<p>Established: <b>{v['side_gate']['established']}</b>. Criterion: {e(v['side_gate']['criterion'])}. Simple Side I − Side II amplitude contrasts did not "
            "separate sides; the wider contrast family (kurtosis, crest, band-energy contrasts per car) does under this protocol.</p>",
            "<h2>Failure cases (seed 0, full set, out-of-fold)</h2>", table([{"truth": t, **row} for t, row in v["experiments"][v["selected"]]["full_set"]["seed0_detail"]["confusion"].items()]),
            table(v["experiments"][v["selected"]]["full_set"].get("seed0_errors", [])),
            "<h2>Conclusion</h2><ul><li><b>Finding:</b> fault files raise vibration on both sides; speed alone would predict Normal for 121 files.</li>"
            "<li><b>Hypothesis:</b> side contrast in higher-order statistics identifies the affected side — gate passed, but files may share acquisition runs (no provenance).</li></ul>"]
    (OUT / "rail.html").write_text(page("Rail EDA", "".join(body)), encoding="utf-8")
    sel = v["experiments"][v["selected"]]
    ledger.append({"id": "RAIL-TWO-STAGE", "formula": "RF on side-aggregated time/spectral features; ET on side-contrast features",
                   "units": "model score", "condition": "speed-free features", "direction/cutoff": "fault score ≥ 0.5; side score ≥ 0.5 ⇒ Side II",
                   "selection partition": "stratified 5-fold × 5 seeds (model-selection validation)", "evaluation partition": "same folds; speed-matched subset",
                   "n": 272, "violations": json.dumps(sel["full_set"]["seed0_detail"]["confusion"]),
                   "metric effect": f"macro F1 full {sel['full_set']['macro_f1_mean']:.3f}, matched {sel['speed_matched']['macro_f1_mean']:.3f}"})


def _shm_example(v, xs, y) -> str:
    lo, hi = int(np.argmin(y)), int(np.argmax(y))
    ser = []
    for k, col in ((lo, "#6b7280"), (hi, "#b42318")):
        x = xs[k][:60000]
        b = x.reshape(-1, 200)
        idx = np.repeat(np.arange(b.shape[0]) * 200, 2)
        vals = np.column_stack([b.min(1), b.max(1)]).ravel()
        ser.append((f"{v['files'][k]} (damage {y[k]:.3f})", idx.tolist(), vals.tolist(), col))
    return lines(ser, "First 60,000 samples of each file (min/max per 200-sample bucket)", "sample index", "stress (unit not documented)")


def shm_report(ledger):
    v = load_json(REPORTS / "validation" / "shm.json")
    y = np.asarray(v["truth"])
    xs = [shm.parse(DATA / "SHM" / "Train" / f).x for f in v["files"]]
    p2p = [float(x.max() - x.min()) for x in xs]
    sel = v["candidates"][v["selected"]]
    pred = np.asarray(sel["predictions"])
    body = ["<h1>SHM — development EDA</h1>",
            f"<div class='fact'>64 training files × 581,120 headerless samples; 16 test files. Damage targets: {e(json.dumps(v['target']))}. "
            "File numbers are random identifiers; sampling rate and unit are undocumented.</div>",
            "<h2>Extreme amplitude carries the signal</h2>",
            scatter(p2p, y, "Peak-to-peak stress range vs damage (training)", "peak-to-peak range", "damage", logx=True, logy=True),
            "<h2>Example traces: lowest vs highest damage</h2>",
            _shm_example(v, xs, y),
            "<h2>Candidates (leave-one-file-out)</h2>",
            table([{"candidate": k, "score": c["score"], "MAPE": c["mape"], "low-half MAPE": c["mape_low_half"], "high-half MAPE": c["mape_high_half"]}
                   for k, c in v["candidates"].items()]),
            f"<p>Selected {e(v['selected'])}: {e(json.dumps(v['final_params']['selected']))}. Fitted exponent m vs the exploratory peak-range prior 4.06. "
            f"Gating: {e(json.dumps(v['gating_effect']))}</p>",
            scatter(y, pred, "Leave-one-out prediction vs truth (selected model)", "true damage", "predicted damage", diag=True, logx=True, logy=True),
            "<h2>Largest relative errors</h2>",
            table(sorted([{"file": f, "true": float(t), "LOO prediction": float(p), "relative error": float(abs(t - p) / t)}
                          for f, t, p in zip(v["files"], y, pred)], key=lambda r: -r["relative error"])[:6]),
            "<h2>Conclusion</h2><ul><li><b>Finding:</b> with full rainflow pairing, Σ n·range^m with m≈5 reproduces the labels closely "
            "(consistent with the reference damage being a Miner/rainflow calculation).</li><li><b>Hypothesis:</b> the fitted constants hold for the held-out "
            "segments from the same measurement point; they are not physically calibrated S–N constants.</li></ul>"]
    (OUT / "shm.html").write_text(page("SHM EDA", "".join(body)), encoding="utf-8")
    fp = v["final_params"]["selected"]
    ledger.append({"id": "SHM-POWER-LAW", "formula": "c·Σ nᵢ·rangeᵢ^m over gated rainflow cycles", "units": "damage (dimensionless)",
                   "condition": f"gate {fp.get('gate')} stress units", "direction/cutoff": f"m={fp.get('m')}, log c={fp.get('log_c', 0):.3f}",
                   "selection partition": "gate and m chosen inside each LOO fold", "evaluation partition": "leave-one-file-out (64)", "n": 64,
                   "violations": "see largest relative errors", "metric effect": f"score {sel['score']:.3f}"})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ledger: list[dict] = []
    door_report(ledger)
    acv_report(ledger)
    rail_report(ledger)
    shm_report(ledger)
    s = load_json(REPORTS / "validation" / "summary.json")
    idx = ["<h1>SENTINEL PS3 — development EDA</h1><p>Reports built from the official training data with the same parsers and features the app uses. "
           "Figures are development evidence, not held-out results.</p><ul>"]
    for t, name in (("door", "Door"), ("acv", "ACV"), ("rail", "Rail corrugation"), ("shm", "SHM")):
        h = s["tasks"].get(t, {})
        idx.append(f"<li><a href='{t}.html'>{name}</a> — {e(h.get('metric'))} {h.get('value', 0):.3f} ({e(h.get('scope'))})</li>")
    idx.append("</ul><p><a href='../evidence_ledger.md'>Threshold and feature evidence ledger</a> · <a href='../section0_facts.json'>Dataset fact reproduction</a> · "
               "<a href='../validation/split_manifest.json'>Split manifest (file hashes per fold)</a> · "
               "<a href='../forecasting_feasibility.md'>Forecasting evaluation</a></p>")
    (OUT / "index.html").write_text(page("SENTINEL EDA", "".join(idx)), encoding="utf-8")
    cols = list(ledger[0])
    md = ["# Threshold and feature evidence ledger", "", f"Generated {now()} by `training/eda_reports.py`. Each row is a hypothesis with its "
          "selection and evaluation partitions. Figures are local development validation.", "",
          "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |" for r in ledger]
    (REPORTS / "evidence_ledger.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
