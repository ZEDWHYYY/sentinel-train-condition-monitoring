"""Door: continuous-stream parsing, gap segmentation, direction inference,
cycle features, direction-conditioned classification (absolute D0 or
stream-relative D2 cutoff) and evidence."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ParseError, Profile, QualityIssue, ReviewReason, chart, minmax_downsample

COLUMNS = [
    "Datetime", "Motor current(mA)", "Motor Voltage(10mV)", "Motor electrodynamic force",
    "Door opening time(.1s)", "Door closing time(.1s)", "Close command", "Open command",
    "DCSR", "DCSL", "DLSR", "DLSL", "Door Opened", "Door Locked", "Door is opening",
    "Door is closing", "Door leaf position",
]
DIGITAL = ["Close command", "Open command", "DCSR", "DCSL", "DLSR", "DLSL", "Door Opened",
           "Door Locked", "Door is opening", "Door is closing"]
ANALOG = ["Motor current(mA)", "Motor Voltage(10mV)", "Motor electrodynamic force", "Door leaf position"]
CURRENT = "Motor current(mA)"
POSITION = "Door leaf position"
LABELS = ("Normal", "Abnormal resistance")


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


_ALIASES = {_norm(c): c for c in COLUMNS}
_ALIASES.update({_norm("Motor current (mA)"): "Motor current(mA)",
                 _norm("Motor Voltage (10mV)"): "Motor Voltage(10mV)",
                 _norm("Motor back electromotive force"): "Motor electrodynamic force",
                 _norm("Door opening time (0.1 s)"): "Door opening time(.1s)",
                 _norm("Door closing time (0.1 s)"): "Door closing time(.1s)"})


def recognize_headers(headers: list[str]) -> tuple[float, dict[str, str]]:
    """Return (fraction of required columns found, mapping source->canonical)."""
    mapping = {}
    for h in headers:
        c = _ALIASES.get(_norm(h))
        if c and c not in mapping.values():
            mapping[h] = c
    return len(mapping) / len(COLUMNS), mapping


def parse_timestamps(values: pd.Series) -> tuple[np.ndarray, list[int]]:
    """Seven numeric components Y-M-D-h-m-s-ms (not zero padded). Returns epoch
    seconds (naive local clock, no timezone invented) and bad row indices."""
    parts = values.astype(str).str.strip().str.split("-", expand=True)
    bad: list[int] = []
    if parts.shape[1] != 7:
        raise ParseError("door_timestamp_format",
                         "Datetime values do not have seven hyphen-separated parts "
                         "(Year-Month-Day-Hour-Minute-Second-Millisecond).",
                         "Export the native Door timestamp format.")
    nums = parts.apply(pd.to_numeric, errors="coerce")
    bounds = [(1900,2200),(1,12),(1,31),(0,23),(0,59),(0,59),(0,999)]
    bad_mask = (nums.isna().any(axis=1) | (nums % 1 != 0).any(axis=1)).to_numpy(copy=True)
    for k,(lo,hi) in enumerate(bounds):
        bad_mask |= (~nums[k].between(lo,hi)).to_numpy()
    bad = np.flatnonzero(bad_mask).tolist()
    n = nums.fillna(0).astype(np.int64)
    dt = pd.to_datetime(dict(year=n[0], month=n[1], day=n[2],
                             hour=n[3], minute=n[4], second=n[5]), errors="coerce")
    secs = (dt.fillna(pd.Timestamp(0)).astype("datetime64[ns]").astype("int64") / 1e9).to_numpy() \
        + n[6].to_numpy() / 1000.0
    secs = secs.astype(float)
    secs[bad_mask | dt.isna().to_numpy()] = np.nan
    bad = sorted(set(bad) | set(np.flatnonzero(dt.isna().to_numpy()).tolist()))
    return secs, bad


@dataclass
class DoorData:
    frame: pd.DataFrame
    t: np.ndarray  # absolute seconds, naive local clock
    raw_time: list[str]
    issues: list[QualityIssue] = field(default_factory=list)
    mapping: dict = field(default_factory=dict)


def parse(path: str | Path) -> DoorData:
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001 - user-facing parse failure
        raise ParseError("unreadable_csv", f"Could not read the file as CSV: {e}",
                         "Check the file is a comma-separated Door export.") from e
    if df.empty:
        raise ParseError("empty_file", "The file has a header but no data rows.", "Upload a non-empty recording.")
    frac, mapping = recognize_headers(list(df.columns))
    if frac < 1.0:
        missing = [c for c in COLUMNS if c not in mapping.values()]
        raise ParseError("door_missing_columns", "Missing required Door columns: " + ", ".join(missing),
                         "Upload an official-format Door stream with all 17 columns.")
    dup = [c for c in df.columns if list(df.columns).count(c) > 1]
    issues: list[QualityIssue] = []
    extra = [c for c in df.columns if c not in mapping]
    df = df.rename(columns=mapping)
    if extra:
        issues.append(QualityIssue("extra_columns", "info",
                                   f"{len(extra)} unrecognised column(s) kept for browsing only: {', '.join(extra[:5])}",
                                   treatment="Not used by the model."))
    if dup:
        raise ParseError("duplicate_columns", f"Duplicate column names: {sorted(set(dup))}", "Rename or remove duplicates.")
    raw_time = df["Datetime"].tolist()
    t, bad_t = parse_timestamps(df["Datetime"])
    out = pd.DataFrame(index=df.index)
    nonnum_rows: set[int] = set()
    for c in COLUMNS[1:]:
        v = pd.to_numeric(df[c].replace("", np.nan), errors="coerce")
        bad = v.isna() & (df[c].astype(str).str.strip() != "")
        nonnum_rows.update(np.flatnonzero(bad.to_numpy()).tolist())
        out[c] = v.astype(float).replace([np.inf,-np.inf],np.nan)
    currents = out[CURRENT].dropna().abs()
    if len(currents) < 2:
        raise ParseError("door_no_current", "Fewer than two finite motor-current samples; resistance cannot be assessed.", "Supply a complete movement with motor current in mA.")
    if currents.max() > 1e6 or (currents.max() > 0 and currents.quantile(.95) < 5):
        raise ParseError("door_current_scale", "Motor current is outside the supported mA scale (possible A/mA mismatch or extreme outlier).", "Verify the sensor units, export current in mA and correct corrupt readings.")
    miss = out.isna().to_numpy()
    if bad_t:
        issues.append(QualityIssue("timestamp_parse_failure", "warning",
                                   f"{len(bad_t)} row(s) have unreadable timestamps.",
                                   rows=[r + 2 for r in bad_t],
                                   treatment="Rows excluded from segmentation.",
                                   effect="Cycles containing these rows may be split or flagged.",
                                   next_step="Correct the Datetime values and re-upload."))
    if nonnum_rows:
        issues.append(QualityIssue("non_numeric_values", "warning",
                                   f"{len(nonnum_rows)} row(s) contain non-numeric sensor values.",
                                   rows=[r + 2 for r in sorted(nonnum_rows)],
                                   treatment="Values kept as missing; not interpolated.",
                                   effect="Features of affected cycles are marked for review."))
    if miss.any():
        frac_m = float(miss.mean())
        issues.append(QualityIssue("missing_values", "warning" if frac_m > 0 else "info",
                                   f"{miss.sum()} missing sensor value(s) ({frac_m:.3%} of cells), measured before cleaning.",
                                   treatment="Not filled; affected cycles flagged for review."))
    order = np.argsort(np.where(np.isnan(t), np.inf, t), kind="stable")
    if np.any(np.diff(t[~np.isnan(t)]) < 0):
        issues.append(QualityIssue("timestamps_out_of_order", "warning",
                                   "Timestamps are not in increasing order.",
                                   treatment="Rows sorted by parsed time with original row numbers kept.",
                                   effect="Check segmentation boundaries."))
    dup_t = int(np.sum(np.diff(np.sort(t[~np.isnan(t)])) == 0))
    if dup_t:
        issues.append(QualityIssue("repeated_timestamps", "warning", f"{dup_t} repeated timestamp(s).",
                                   treatment="Kept in recorded order; no deduplication.",
                                   effect="Integrals over repeated rows use zero elapsed time."))
    keep = order[~np.isnan(t[order])]
    if len(keep) < 2 or np.ptp(t[keep]) <= 0:
        raise ParseError("door_too_short", "Fewer than two distinct valid timestamps remain.", "Upload a complete door movement with valid native timestamps.")
    out = out.iloc[keep].reset_index(drop=False).rename(columns={"index": "source_row"})
    out["source_row"] = out["source_row"] + 2  # 1-based file line incl. header
    return DoorData(frame=out, t=t[keep], raw_time=[raw_time[i] for i in keep], issues=issues,
                    mapping=mapping)


def profile(d: DoorData) -> Profile:
    dts = np.diff(d.t)
    within = dts[(dts > 0) & (dts < 1.0)]
    rate = 1.0 / float(np.median(within)) if len(within) else None
    chans = []
    for c in COLUMNS[1:]:
        v = d.frame[c].to_numpy()
        fin = v[np.isfinite(v)]
        chans.append({"name": c, "kind": "state" if c in DIGITAL else "analog",
                      "min": float(fin.min()) if len(fin) else None,
                      "median": float(np.median(fin)) if len(fin) else None,
                      "max": float(fin.max()) if len(fin) else None,
                      "missing": int(len(v) - len(fin))})
    return Profile(rows=len(d.frame), columns=len(COLUMNS), sample_rate_hz=rate,
                   sample_rate_source="measured median in-cycle row spacing",
                   coverage=f"{d.raw_time[0]} to {d.raw_time[-1]} (recorded clock, timezone unknown)",
                   channels=chans,
                   missing_fraction=float(d.frame[COLUMNS[1:]].isna().to_numpy().mean()))


# ---------------------------------------------------------------- segmentation

def segment(t: np.ndarray, gap_threshold_s: float, review_band: tuple[float, float]) -> dict:
    dts = np.diff(t)
    cuts = np.flatnonzero(dts > gap_threshold_s)
    starts = np.concatenate([[0], cuts + 1])
    ends = np.concatenate([cuts, [len(t) - 1]])
    band = np.flatnonzero((dts > review_band[0]) & (dts < review_band[1]))
    hist_edges = [0, 0.03, 0.1, 1, 10, 30, 60, 1e9]
    hist = np.histogram(dts, bins=hist_edges)[0].tolist() if len(dts) else []
    return {"segments": list(zip(starts.tolist(), ends.tolist())),
            "band_gaps": [{"after_row_index": int(i), "gap_s": float(dts[i])} for i in band],
            "gap_histogram": {"edges_s": hist_edges[:-1] + ["inf"], "counts": hist},
            "min_between_gap_s": float(dts[cuts].min()) if len(cuts) else None,
            "max_within_gap_s": float(dts[dts <= gap_threshold_s].max()) if np.any(dts <= gap_threshold_s) else None}


# ---------------------------------------------------------------- direction

def infer_direction(cyc: pd.DataFrame, position_sign: dict[str, int]) -> tuple[str | None, dict]:
    """Vote from four independent cues; any disagreement leaves it unresolved."""
    votes = {}
    oc, cc = cyc["Open command"].mean(), cyc["Close command"].mean()
    votes["command"] = "Open" if oc > 0.5 and cc < 0.5 else "Close" if cc > 0.5 and oc < 0.5 else None
    op, cl = cyc["Door is opening"].mean(), cyc["Door is closing"].mean()
    votes["motion_flag"] = "Open" if op > 0.5 and cl < 0.5 else "Close" if cl > 0.5 and op < 0.5 else None
    d0, d1 = cyc["DCSR"].iloc[0] + cyc["DCSL"].iloc[0], cyc["DCSR"].iloc[-1] + cyc["DCSL"].iloc[-1]
    votes["close_switch"] = "Close" if d1 > d0 else "Open" if d0 > d1 else None
    pos = cyc[POSITION].to_numpy()
    fin = pos[np.isfinite(pos)]
    if len(fin) >= 2 and abs(fin[-1] - fin[0]) > 50:
        sign = int(np.sign(fin[-1] - fin[0]))
        votes["position_trend"] = next((k for k, s in position_sign.items() if s == sign), None)
    else:
        votes["position_trend"] = None
    cast = {v for v in votes.values() if v is not None}
    decided = cast.pop() if len(cast) == 1 and sum(v is not None for v in votes.values()) >= 2 else None
    return decided, votes


# ---------------------------------------------------------------- features

def cycle_features(cyc: pd.DataFrame, t: np.ndarray) -> dict:
    cur = cyc[CURRENT].to_numpy()
    dt = np.diff(t)
    step = float(np.median(dt)) if len(dt) else 0.02
    w = np.append(dt, step)
    fin = np.isfinite(cur)
    pos = cyc[POSITION].to_numpy()
    pf = pos[np.isfinite(pos)]
    return {
        "current_integral_mAs": float(np.sum(np.where(fin, cur, 0) * w)),
        "mean_current_mA": float(np.nanmean(cur)) if fin.any() else None,
        "peak_current_mA": float(np.nanmax(cur)) if fin.any() else None,
        "p90_current_mA": float(np.nanpercentile(cur, 90)) if fin.any() else None,
        "duration_s": float(t[-1] - t[0] + step),
        "rows": int(len(cyc)),
        "position_travel": float(abs(pf[-1] - pf[0])) if len(pf) >= 2 else None,
        "missing_current_rows": int((~fin).sum()),
    }


# ---------------------------------------------------------------- inference

def stream_baselines(cycles: list[tuple[dict, str | None]], model: dict) -> dict[str, dict]:
    """D2: per-direction baseline of *this* recording (a low percentile of its cycle integrals).

    A ratio rule transfers between doors whose Normal current level differs (Door Info Kit 1.2).
    The baseline is only trusted when the direction has enough cycles and the baseline is
    plausible against the training door; otherwise the absolute D0 cutoff is used and flagged.
    """
    rel = model.get("relative_rule")
    out: dict[str, dict] = {}
    if not rel:
        return out
    q, min_n = rel["baseline_percentile"], rel["min_cycles_per_direction"]
    lo, hi = rel["plausibility_window"]
    for op in ("Open", "Close"):
        xs = [f["current_integral_mAs"] for f, dr in cycles if dr == op and f["current_integral_mAs"] is not None]
        r = rel["directions"][op]
        if len(xs) < min_n:
            out[op] = {"baseline": None, "reason": f"only {len(xs)} {op.lower()} cycles in this recording (need {min_n})", "n": len(xs)}
            continue
        b = float(np.percentile(xs, q))
        ratio = b / r["normal_median"]
        if not (lo <= ratio <= hi):
            out[op] = {"baseline": None, "n": len(xs), "value": b,
                       "reason": f"{op.lower()} baseline {b:.0f} mA·s is {ratio:.2f}× the training Normal level, outside the plausible window {lo}–{hi}× "
                                 "(the recording may be mostly abnormal or in different units)"}
            continue
        out[op] = {"baseline": b, "n": len(xs), "ratio_to_training": ratio, "reason": None}
    return out


def classify(feats: dict, direction: str | None, model: dict, baselines: dict[str, dict] | None = None) -> tuple[str, list[ReviewReason], dict]:
    x = feats["current_integral_mAs"]
    rng = model["class_ranges"]
    base = (baselines or {}).get(direction or "", {})
    rel = model.get("relative_rule")
    if direction is not None and rel and base.get("baseline") is not None:
        b = base["baseline"]
        r = rel["directions"][direction]
        cut = b * r["ratio_cutoff"]
        n_hi = b * r["normal_ratio_max"]
        a_lo = b * r["abnormal_ratio_min"]
        basis = f"{direction} cutoff relative to this recording's baseline"
        detail = {"cutoff": cut, "basis": basis, "normal_max": n_hi, "abnormal_min": a_lo, "rule": "relative",
                  "baseline": b, "ratio": x / b if b else None, "ratio_cutoff": r["ratio_cutoff"]}
    elif direction is not None:
        cut = model["cutoffs"][direction]
        n_hi = rng[direction]["Normal"][1]
        a_lo = rng[direction]["Abnormal resistance"][0]
        basis = f"{direction} absolute cutoff"
        detail = {"cutoff": cut, "basis": basis, "normal_max": n_hi, "abnormal_min": a_lo, "rule": "absolute"}
    else:
        cut = model["pooled_cutoff"]
        n_hi = max(r["Normal"][1] for r in rng.values())
        a_lo = min(r["Abnormal resistance"][0] for r in rng.values())
        basis = "pooled absolute cutoff (direction unresolved)"
        detail = {"cutoff": cut, "basis": basis, "normal_max": n_hi, "abnormal_min": a_lo, "rule": "absolute"}
    label = LABELS[1] if x > cut else LABELS[0]
    reasons: list[ReviewReason] = []
    lo, hi = min(n_hi, a_lo), max(n_hi, a_lo)
    if lo < x < hi:
        if detail["rule"] == "relative":
            msg = (f"Current integral {x:.0f} mA·s is {detail['ratio']:.3f}× this recording's {direction.lower()} baseline, between the highest "
                   f"Normal ({r['normal_ratio_max']:.3f}×) and lowest Abnormal ({r['abnormal_ratio_min']:.3f}×) ratios seen in training — no training cycle lies here.")
        else:
            msg = (f"Current integral {x:.0f} mA·s lies between the highest Normal ({n_hi:.0f}) and lowest "
                   f"Abnormal ({a_lo:.0f}) training values for this direction — no training cycle lies here.")
        reasons.append(ReviewReason("near_boundary", msg,
                                    "Compare this cycle's current trace with the Normal reference and inspect a repeat cycle of the same door.", "current"))
    if direction is not None and rel and base.get("baseline") is None:
        reasons.append(ReviewReason(
            "baseline_unavailable",
            f"This recording's own {direction.lower()} baseline could not be used ({base.get('reason', 'unknown')}); "
            "the absolute training-door cutoff was applied instead.",
            "Check whether the recording covers enough normal movements of this door; compare against a longer recording.", "current"))
    return label, reasons, detail


def analyze(d: DoorData, model: dict) -> dict:
    cfg = model["segmentation"]
    seg = segment(d.t, cfg["gap_threshold_s"], tuple(cfg["review_band_s"]))
    band_rows = {g["after_row_index"] for g in seg["band_gaps"]}
    travel_min = model["position_travel_min"]
    items = []
    prepared = []
    for a, b in seg["segments"]:
        cyc = d.frame.iloc[a:b + 1]
        tt = d.t[a:b + 1]
        feats = cycle_features(cyc, tt)
        if feats["missing_current_rows"] >= max(1, len(cyc) * .2):
            raise ParseError("door_cycle_missing_current", f"Movement at {d.raw_time[a]} has at least 20% missing motor-current samples; resistance cannot be classified reliably.", "Restore the missing current values or upload a complete repeat recording.")
        direction, votes = infer_direction(cyc, model["position_sign"])
        prepared.append((a, b, cyc, tt, feats, direction, votes))
    baselines = stream_baselines([(f, dr) for _, _, _, _, f, dr, _ in prepared], model)
    for k, (a, b, cyc, tt, feats, direction, votes) in enumerate(prepared):
        label, reasons, detail = classify(feats, direction, model, baselines)
        if direction is None:
            reasons.insert(0, ReviewReason(
                "direction_unresolved",
                "Opening/closing direction could not be established consistently from the commands, "
                f"motion flags, close switches and position trend (votes: {votes}).",
                "Check the command and door-position channels for this interval; the pooled cutoff was used.",
                "position"))
        if feats["position_travel"] is None or feats["position_travel"] < travel_min:
            reasons.append(ReviewReason(
                "partial_cycle",
                f"Door position travelled {feats['position_travel'] or 0:.0f} units, less than the "
                f"{travel_min:.0f} seen in every training cycle — the movement may be truncated.",
                "Check whether the recording starts or ends mid-movement; obtain the complete cycle.",
                "position"))
        if feats["missing_current_rows"]:
            reasons.append(ReviewReason(
                "missing_data", f"{feats['missing_current_rows']} motor-current sample(s) missing in this cycle.",
                "Inspect the affected rows; the integral excludes them and may be understated.", "current"))
        if any(a <= r < b for r in band_rows) or (a - 1) in band_rows or b in band_rows:
            reasons.append(ReviewReason(
                "ambiguous_gap",
                "A time gap between 0.03 s and 10 s occurs at or inside this cycle — outside the "
                "gap regimes seen in training, so the boundary may be wrong.",
                "Inspect the timeline around this cycle's boundaries.", "timeline"))
        items.append({
            "id": f"cycle-{k + 1:03d}",
            "index": k,
            "start_time": d.raw_time[a],
            "end_time": d.raw_time[b],
            "t0": float(d.t[a]),
            "t1": float(d.t[b]),
            "row_range": [int(d.frame["source_row"].iloc[a]), int(d.frame["source_row"].iloc[b])],
            "prediction": label,
            "operation": direction,
            "direction_votes": votes,
            "features": feats,
            "decision": detail,
            "review_reasons": [r.to_dict() for r in reasons],
            "evidence_state": "review_suggested" if reasons else "no_trigger",
            "observations": _observations(feats, direction, label, detail, model),
        })
    stream_notes = []
    for op in ("Open", "Close"):
        ops = [i for i in items if i["operation"] == op]
        between = [i for i in ops if any(r["code"] == "near_boundary" for r in i["review_reasons"])]
        if ops and len(between) / len(ops) >= 0.2:
            stream_notes.append(
                f"{len(between)} of {len(ops)} {op.lower()} cycles fall between the training Normal and Abnormal ranges. "
                "This door or its condition may differ from the single training door; treat labels near the cutoff as uncertain.")
        bl = baselines.get(op, {})
        if model.get("relative_rule") and ops and bl.get("baseline") is None:
            stream_notes.append(f"The {op.lower()} cutoff fell back to the training door's absolute value: {bl.get('reason', 'baseline unavailable')}.")
    n_abn = sum(i["prediction"] == LABELS[1] for i in items)
    n_rev = sum(bool(i["review_reasons"]) for i in items)
    headline = (f"{n_abn} of {len(items)} cycles predicted Abnormal resistance" if n_abn
                else f"No abnormal resistance predicted in {len(items)} cycles of this recording")
    return {
        "task": "door",
        "headline": headline,
        "summary": {"cycles": len(items), "abnormal": n_abn, "normal": len(items) - n_abn,
                    "review": n_rev, "stream_notes": stream_notes, "baselines": baselines,
                    "segmentation": {k: v for k, v in seg.items() if k != "segments"}},
        "items": items,
    }


def _observations(feats: dict, direction: str | None, label: str, detail: dict, model: dict) -> list[str]:
    x = feats["current_integral_mAs"]
    obs = []
    if direction and detail.get("rule") == "relative":
        r = model["class_ranges"][direction]["Normal"]
        obs.append(f"Motor-current integral was {x:.0f} mA·s during this {direction.lower()} movement — {detail['ratio']:.3f}× this recording's own "
                   f"{direction.lower()} baseline of {detail['baseline']:.0f} mA·s (the training door's Normal {direction.lower()} cycles were "
                   f"{r[0]:.0f}–{r[1]:.0f} mA·s).")
    elif direction:
        r = model["class_ranges"][direction]["Normal"]
        n = model["class_counts"][direction]["Normal"]
        obs.append(f"Motor-current integral was {x:.0f} mA·s during this {direction.lower()} movement, "
                   f"compared with {r[0]:.0f}–{r[1]:.0f} mA·s for Normal training {direction.lower()} cycles (n={n}).")
    else:
        obs.append(f"Motor-current integral was {x:.0f} mA·s; direction was unresolved so the pooled cutoff "
                   f"{detail['cutoff']:.0f} mA·s was used.")
    if label == LABELS[1]:
        obs.append(f"This is above the frozen {detail['basis']} of {detail['cutoff']:.0f} mA·s, which supports an "
                   "abnormal-resistance prediction. The recording does not identify the cause (e.g. obstruction, jamming or deformation).")
    else:
        obs.append(f"This is at or below the frozen {detail['basis']} of {detail['cutoff']:.0f} mA·s, consistent with Normal resistance.")
    obs.append(f"Movement lasted {feats['duration_s']:.2f} s; peak current {feats['peak_current_mA']:.0f} mA "
               "(duration and peak did not separate the classes in training).")
    return obs


# ---------------------------------------------------------------- evidence

def timeline_chart(result: dict, source: str) -> dict:
    items = result["items"]
    if not items:
        return chart("Cycle timeline", "cycles", "", "Recorded time", source, [], kind="timeline")
    t0 = items[0]["t0"]
    bands = [{"x0": i["t0"] - t0, "x1": i["t1"] - t0, "id": i["id"],
              "label": i["prediction"], "review": bool(i["review_reasons"]),
              "tone": "fault" if i["prediction"] == LABELS[1] else "normal"} for i in items]
    return chart("Cycle timeline", "Detected door cycles", "s", f"Seconds since {items[0]['start_time']}",
                 source, [], bands=bands, kind="timeline",
                 caption="Each band is one detected opening or closing movement. Red = predicted abnormal "
                         "resistance, grey = Normal, amber outline = review suggested. Select a cycle to see its signals.")


def cycle_chart(d: DoorData, item: dict, model: dict, source: str, max_points: int = 1200) -> list[dict]:
    a = int(np.searchsorted(d.t, item["t0"]))
    b = int(np.searchsorted(d.t, item["t1"], side="right"))
    cyc = d.frame.iloc[a:b]
    x = d.t[a:b] - d.t[a]
    cur = cyc[CURRENT].to_numpy()
    pos = cyc[POSITION].to_numpy()
    ref = model.get("reference", {}).get(item["operation"] or "", None)
    series = [{"name": "This cycle", "role": "primary", **minmax_downsample(x, cur, max_points)}]
    bands = []
    ref_label = None
    if ref:
        rx = np.arange(len(ref["p50"])) * ref["step_s"]
        n = min(len(rx), int(max(x[-1] if len(x) else 0, 0) / ref["step_s"]) + 40)
        series.append({"name": "Normal reference median", "role": "reference",
                       "x": rx[:n].tolist(), "min": ref["p50"][:n], "max": ref["p50"][:n], "aggregated": False})
        series.append({"name": "Normal reference 10–90th percentile", "role": "band",
                       "x": rx[:n].tolist(), "min": ref["p10"][:n], "max": ref["p90"][:n], "aggregated": False})
        ref_label = f"Normal training {item['operation'].lower()} cycles (n={ref['n']}), aligned at movement start"
    rows = f"rows {item['row_range'][0]}–{item['row_range'][1]}"
    c1 = chart(f"Motor current — {item['id']}", "Motor current", "mA", "Seconds since cycle start",
               f"{source}, {rows}", series, reference=ref_label, bands=bands,
               caption="The reference band is a range of Normal training cycles, not a confidence interval.")
    c2 = chart(f"Door leaf position — {item['id']}", "Door leaf position", "unknown unit (undocumented)",
               "Seconds since cycle start", f"{source}, {rows}",
               [{"name": "Position", "role": "primary", **minmax_downsample(x, pos, max_points)}])
    return [c1, c2]


def export_rows(result: dict) -> list[dict]:
    return [{"start_time": i["start_time"], "end_time": i["end_time"], "prediction": i["prediction"]}
            for i in sorted(result["items"], key=lambda i: i["t0"])]


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["start_time", "end_time", "prediction"])
        w.writeheader()
        w.writerows(rows)
