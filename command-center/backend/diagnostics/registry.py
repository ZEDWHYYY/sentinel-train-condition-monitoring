"""Subsystem recognition and the single analyze/evidence entry point shared by
the app worker and the command-line predictor."""
from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from typing import Callable

from . import acv, door, rail, shm, recommendations
from .common import FEATURE_VERSION, PARSER_VERSION, SUBSYSTEM_LABELS, ParseError, finite
from .model_store import ModelUnavailable, load_model

# Review-policy versions (part of the repeat key): door 1.1 adds baseline_unavailable; acv 1.1 adds hot_period_disagreement.
REVIEW_POLICY = {"door": "1.1", "acv": "1.1", "rail": "1.0", "shm": "1.0"}

TASK_DESCRIPTIONS = {
    "door": "Find each door opening/closing cycle in a continuous recording and classify its resistance.",
    "acv": "Rank the eight cars of a case by likelihood of a refrigerant leak.",
    "rail": "Classify a 1-second axle-box recording as Normal, Side I or Side II corrugation.",
    "shm": "Estimate cumulative fatigue damage for a stress segment.",
}
FORMATS = {"door": "CSV (17 columns, continuous stream)", "acv": "Excel .xlsx case workbook (or flat CSV with the same headers)",
           "rail": "CSV (speed pulse + 128 axle-box channels, 10 kHz, 1 s)", "shm": "CSV, one headerless stress column"}


def _head_lines(path: Path, n: int = 3) -> list[str]:
    with open(path, "rb") as f:
        raw = f.read(64 * 1024)
    text = raw.decode("utf-8-sig", errors="replace")
    return text.splitlines()[:n]


def recognize(path: Path, original_name: str) -> dict:
    """Classify a file into recognised / exploration-only / unreadable."""
    ext = Path(original_name).suffix.lower()
    if ext in (".xlsx",):
        try:
            cands = acv.sheet_candidates(path)
        except ParseError as e:
            return {"path": "unreadable", "subsystem": None, "reason": e.message, "suggestion": e.suggestion}
        compat = [c for c in cands if c["compatible"]]
        if compat:
            out = {"path": "recognized", "subsystem": "acv", "confidence": "header",
                   "reason": f"Workbook sheet(s) with per-car headers: {', '.join(c['sheet'] for c in compat)}",
                   "sheets": cands, "preview": {"cars": compat[0]["cars"]}}
            if len(compat) > 1:
                out["needs"] = {"question": "Which sheet holds the case to analyse?", "field": "sheet",
                                "options": [c["sheet"] for c in compat]}
            return out
        return {"path": "exploration", "subsystem": None, "reason": "No sheet has 'Car <NN> - <parameter>' headers.",
                "sheets": cands}
    if ext in (".xlsm", ".xls", ".xlsb"):
        return {"path": "unreadable", "subsystem": None, "reason": f"{ext} workbooks are not accepted.",
                "suggestion": "Save as a plain .xlsx without macros."}
    if ext not in (".csv", ".txt"):
        return {"path": "unreadable", "subsystem": None, "reason": f"Unsupported file type '{ext or 'none'}'.",
                "suggestion": "Upload CSV files (or .xlsx for ACV)."}
    try:
        lines = _head_lines(path)
    except OSError as e:
        return {"path": "unreadable", "subsystem": None, "reason": str(e)}
    if not lines:
        return {"path": "unreadable", "subsystem": None, "reason": "The file is empty.", "suggestion":"Upload a recording with headers and data rows (SHM accepts a headerless stress column)."}
    header = next(csv.reader(io.StringIO(lines[0])))
    preview_rows = [next(csv.reader(io.StringIO(ln))) for ln in lines[1:3]]
    frac, _ = door.recognize_headers(header)
    if frac == 1.0:
        return {"path": "recognized", "subsystem": "door", "confidence": "header",
                "reason": "All 17 Door columns present.", "preview": {"columns": header, "rows": preview_rows}}
    if any(acv.CAR_RE.match(h) for h in header):
        return {"path":"recognized","subsystem":"acv","confidence":"header","reason":"Per-car ACV telemetry columns detected.","preview":{"columns":header[:10],"rows":[r[:10] for r in preview_rows]}}
    if any(rail.CH_RE.match(h) for h in header):
        sp, cmap, method = rail.channel_map(header)
        if len(cmap) == 128:
            return {"path": "recognized", "subsystem": "rail",
                    "confidence": "header" if method.startswith("semantic") else "column count",
                    "reason": f"129 columns; channels mapped by {method}.",
                    "preview": {"columns": header[:5] + ["…"], "rows": [r[:5] for r in preview_rows]}}
        return {"path":"recognized","subsystem":"rail","reason":f"Rail headers detected; checking all required channels ({len(cmap)} found)."}
    if len(header)>1 and header[0].strip().lower()=="stress":
        return {"path":"recognized","subsystem":"shm","confidence":"header","reason":"Named stress column with auxiliary columns."}
    if len(header) == 1:
        try:
            float(header[0])
            numeric_first = True
        except ValueError:
            numeric_first = False
        rows = [lines[0]] + lines[1:3] if numeric_first else lines[1:3]
        return {"path": "recognized" if numeric_first else "needs_confirmation", "subsystem": "shm",
                "confidence": "single numeric column",
                "reason": ("One headerless numeric column, matching the SHM stress format. Row 1 is kept as data."
                           if numeric_first else "One column with a text header; confirm it is SHM stress."),
                "preview": {"first_values": rows},
                "needs": None if numeric_first else {"question": "Is this column dynamic stress from an SHM measurement point?",
                                                     "field": "subsystem", "options": ["shm"]}}
    if frac > 0.5:
        return {"path": "recognized", "subsystem": "door",
                "reason": f"Only {frac:.0%} of the Door columns were found.",
                "suggestion": "Include all 17 Door columns to enable prediction.", "preview": {"columns": header}}
    return {"path": "exploration", "subsystem": None,
            "reason": f"{len(header)} columns did not match any supported subsystem schema.",
            "suggestion": "Choose the subsystem explicitly if this is an official export; otherwise it can only be explored.",
            "preview": {"columns": header[:12]}}


def validate_upload(rec: dict, path: Path, sheet: str | None = None) -> dict:
    """Full parse/profile before claiming that a recognized upload is ready."""
    if not rec.get("subsystem") or rec.get("needs"):
        return rec
    try:
        data=parsed(rec["subsystem"],path,sheet)
        p=profile_of(rec["subsystem"],data)
        return finite({**rec,"validation":p,"issues":[i.to_dict() for i in data.issues]})
    except ParseError as e:
        return {**rec,"path":"unreadable","reason":e.message,"suggestion":e.suggestion,"code":e.code}


def preview_of(sub: str, data) -> dict:
    """A bounded preview of parsed values, with original indices where available."""
    if sub=="door":
        cols=["Datetime",door.CURRENT,door.POSITION,"source_row"]
        rows=[[data.raw_time[i],float(data.frame[door.CURRENT].iloc[i]),float(data.frame[door.POSITION].iloc[i]),int(data.frame.source_row.iloc[i])] for i in range(min(8,len(data.t)))]
    elif sub=="acv":
        cols=["Time"]+[f"Car {c} cabin (°C assumed)" for c in data.cars]
        rows=[[str(data.time.iloc[i])]+[float(data.signals["indoor"][c].iloc[i]) for c in data.cars] for i in range(min(8,len(data.time)))]
    elif sub=="rail":
        cols=["Sample","Time (s)","Speed pulse","Car 1 pos 1 vibration (m/s²)","Car 1 pos 2 vibration (m/s²)"]
        rows=[[i,i/rail.FS,float(data.data[i,data.speed_col]),float(data.data[i,data.cmap[(1,1,"vibration")]]),float(data.data[i,data.cmap[(1,2,"vibration")]])] for i in range(min(8,len(data.data)))]
    else:
        cols=["Original sample index","Stress (unit undocumented)"]
        rows=[[int(data.sample_index[i]),float(data.x[i])] for i in range(min(8,len(data.x)))]
    return finite({"columns":cols,"rows":rows})


# ---------------------------------------------------------------- analysis

@lru_cache(maxsize=6)
def _parsed(subsystem: str, path: str, sheet: str | None, mtime: float):
    if subsystem == "door":
        return door.parse(path)
    if subsystem == "acv":
        return acv.parse(path, sheet)
    if subsystem == "rail":
        return rail.parse(path)
    if subsystem == "shm":
        return shm.parse(path)
    raise ValueError(subsystem)


def parsed(subsystem: str, path: Path, sheet: str | None = None):
    return _parsed(subsystem, str(path), sheet, Path(path).stat().st_mtime)


def profile_of(subsystem: str, data) -> dict:
    mod = {"door": door, "acv": acv, "rail": rail, "shm": shm}[subsystem]
    return mod.profile(data).to_dict()


def versions(subsystem: str) -> dict:
    try:
        m = load_model(subsystem)
        mv = m["version"]
    except ModelUnavailable:
        mv = None
    return {"parser": PARSER_VERSION, "features": FEATURE_VERSION, "model": mv, "policy": f"{subsystem}-review-{REVIEW_POLICY[subsystem]}+{recommendations.VERSION}"}


def analyze_file(subsystem: str, path: Path, file_id: str, sheet: str | None = None,
                 stage: Callable[[str], None] = lambda s: None) -> dict:
    """Parse -> profile -> features -> frozen predictor -> evidence/review.
    Raises ParseError for unreadable input; returns availability=False when
    the model is missing (descriptive analysis is still returned)."""
    stage("Checking file")
    data = parsed(subsystem, path, sheet)
    issues = [i.to_dict() for i in data.issues]
    stage("Summarizing signals")
    prof = profile_of(subsystem, data)
    try:
        model = load_model(subsystem)
    except ModelUnavailable as e:
        return finite({"available": False, "unavailable_reason": str(e), "profile": prof, "issues": issues,
                       "task": subsystem, "items": [], "headline": "Prediction unavailable: no frozen model installed",
                       "summary": {}, "model_version": None})
    stage("Preparing diagnostic features")
    if subsystem == "door":
        res = door.analyze(data, model)
        stage("Generating results")
        res["overview_chart"] = door.timeline_chart(res, file_id)
    elif subsystem == "acv":
        res = acv.analyze(data, model)
        stage("Generating results")
        res["overview_chart"] = acv.score_chart(res["items"][0])
    elif subsystem == "rail":
        item = rail.analyze_file(data, file_id, model)
        stage("Generating results")
        res = {"task": "rail", "headline": _rail_headline(item), "items": [item],
               "summary": {"prediction": item["prediction"], "review": 1 if item["review_reasons"] else 0},
               "overview_chart": rail.sides_chart(item, file_id)}
    else:
        item = shm.analyze_file(data, file_id, model)
        stage("Generating results")
        res = {"task": "shm", "headline": (f"Estimated cumulative damage {item['prediction']:.4g}" if item["available"]
                                           else "Prediction unavailable"),
               "items": [item], "summary": {"prediction": item["prediction"], "review": 1 if item["review_reasons"] else 0},
               "available": item["available"]}
    stage("Preparing charts")
    res.setdefault("available", True)
    res["profile"] = prof
    res["issues"] = issues
    res["model_version"] = model["version"]
    res["method_name"] = model["method_name"]
    res["quality_state"] = quality_state(issues, res["available"])
    res["preview"] = preview_of(subsystem,data)
    res["diagnosis"] = recommendations.build(subsystem,data,res,model)
    return finite(res)


def _rail_headline(item: dict) -> str:
    if item["prediction"] == "Normal":
        return "No target corrugation signature detected in this recording"
    return f"{item['prediction']} corrugation predicted"


def quality_state(issues: list[dict], available: bool) -> str:
    if not available:
        return "prediction_unavailable"
    if any(i["severity"] in ("warning", "blocking") for i in issues):
        return "usable_with_limitations"
    return "usable"


def evidence(subsystem: str, path: Path, result: dict, item_id: str | None, view: str, params: dict,
             source: str, sheet: str | None = None) -> list[dict]:
    """Bounded chart payloads for one item, recomputed from the stored input."""
    data = parsed(subsystem, path, sheet)
    model = load_model(subsystem)
    items = {i["id"]: i for i in result.get("items", [])}
    if subsystem == "door":
        if item_id is None:
            return [result["overview_chart"]]
        return door.cycle_chart(data, items[item_id], model, source)
    if subsystem == "acv":
        it = result["items"][0]
        car = params.get("car") or it["leading_car"] or data.cars[0]
        charts = [acv.car_chart(data, car, source)]
        if params.get("compare"):
            charts.append(acv.car_chart(data, params["compare"], source))
        return charts
    if subsystem == "rail":
        it = result["items"][0]
        car = int(params.get("car", 1))
        pos = int(params.get("pos", 1))
        kind = params.get("kind", "vibration")
        if view == "psd":
            return [rail.psd_chart(data, car, pos, kind, model, source)]
        if view == "waveform":
            t0 = float(params.get("t0", 0))
            t1 = params.get("t1")
            return [rail.waveform_chart(data, car, pos, kind, source, t0, float(t1) if t1 is not None else None)]
        return [rail.sides_chart(it, source)]
    it = result["items"][0]
    charts = []
    if view in ("trace", "default"):
        i0 = int(params.get("i0", 0))
        i1 = params.get("i1")
        charts.append(shm.trace_chart(data, source, i0, int(i1) if i1 is not None else None))
    if view in ("cycles", "default"):
        r, _, _ = shm.cycles(data.x, model["gate"])
        charts.append(shm.cycle_hist_chart(it, r, model, source))
    return charts


def subsystem_catalog() -> list[dict]:
    out = []
    for s in ("door", "acv", "rail", "shm"):
        try:
            m = load_model(s)
            avail = {"available": True, "version": m["version"], "method": m["method_name"]}
        except ModelUnavailable as e:
            avail = {"available": False, "reason": str(e)}
        out.append({"id": s, "label": SUBSYSTEM_LABELS[s], "task": TASK_DESCRIPTIONS[s], "formats": FORMATS[s],
                    "model": avail})
    return out
