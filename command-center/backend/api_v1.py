"""Versioned diagnostic API."""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

import jobs
import storage
from diagnostics import exports, registry, triage
from diagnostics.common import (ARTIFACT_DIR, DATASET_ROOT, REPO_ROOT, SUBSYSTEM_LABELS, ParseError, chart, finite,
                                load_json, minmax_downsample, sha256_file)
from diagnostics.model_store import ModelUnavailable

router = APIRouter(prefix="/api/v1")

MAX_FILE = int(os.environ.get("SENTINEL_MAX_FILE_MB", "128")) * 1024 * 1024
MAX_BATCH = int(os.environ.get("SENTINEL_MAX_BATCH_MB", "2048")) * 1024 * 1024
CHUNK = 1 << 20
ASSESSMENTS = {"agrees", "disagrees", "needs_more_evidence", "leave_for_later", "note"}
PRIORITIES = {"unassessed", "planned_review", "urgent_assessment"}
POLICY_KEY = "triage_policy"
# "any" (local use): read files anywhere on this computer. Any other value (hosted deployments set
# "dataset"): read only inside DATASET_ROOT, so visitors cannot make the server read its own files.
LOCAL_PATHS = os.environ.get("SENTINEL_LOCAL_PATHS", "any")


def _policy() -> dict:
    return triage.merge_policy(storage.get_setting(POLICY_KEY))


def _latest(kind_rows: list[dict]) -> dict[str, dict[str, dict]]:
    """reviews rows -> {kind: {item_id: latest row}} (rows must be ordered by revision)."""
    out: dict[str, dict[str, dict]] = {}
    for r in kind_rows:
        out.setdefault(r["kind"], {})[r["item_id"]] = r
    return out


def err(status: int, code: str, message: str, suggestion: str = "", field: str | None = None, recoverable=True):
    raise HTTPException(status, {"code": code, "message": message, "suggestion": suggestion, "field": field,
                                 "recoverable": recoverable})


def _run_or_404(run_id: str) -> dict:
    r = storage.get("runs", run_id)
    if r is None:
        err(404, "run_not_found", f"No analysis with id {run_id}.")
    return r


def _result_or_404(rid: str) -> dict:
    r = storage.get("results", rid)
    if r is None:
        err(404, "result_not_found", f"No result with id {rid}.")
    return r


# ---------------------------------------------------------------- catalog

@router.get("/subsystems")
def subsystems():
    return {"subsystems": registry.subsystem_catalog(),
            "limits": {"max_file_mb": MAX_FILE // (1024 * 1024), "max_batch_mb": MAX_BATCH // (1024 * 1024)}}


@router.get("/datasets")
def datasets():
    """Official local dataset folders usable through local-path ingest."""
    base = DATASET_ROOT
    out = []
    for sub, label, path, pat in (
        ("door", "Door — official test stream", "Door/Test.csv", None),
        ("acv", "ACV — official test case", "ACV/Test", "*.xlsx"),
        ("rail", "Rail — official test set (68 files)", "Rail_Corrugation/Test", "*.csv"),
        ("shm", "SHM — official test set (16 files)", "SHM/Test", "*.csv"),
        ("door", "Door — training stream (labelled training example)", "Door/Train.csv", None),
        ("acv", "ACV — training cases (labelled training examples)", "ACV/Train", "*.xlsx"),
        ("shm", "SHM — training files (labelled training examples)", "SHM/Train", "*.csv"),
    ):
        p = base / path
        if p.exists():
            n = 1 if p.is_file() else len(list(p.glob(pat)))
            out.append({"subsystem": sub, "label": label, "path": str(p), "files": n,
                        "training_example": "Train" in path})
    return {"datasets": out, "root": str(base)}


# ---------------------------------------------------------------- runs

@router.post("/runs")
def create_run(payload: dict = Body(default={})):
    sub = payload.get("subsystem")
    if sub is not None and sub not in SUBSYSTEM_LABELS:
        err(400, "unknown_subsystem", f"Unknown subsystem {sub!r}.", field="subsystem")
    rid = storage.new_id("run")
    storage.insert("runs", id=rid, subsystem=sub, purpose=payload.get("purpose", "analysis"), state="draft",
                   created=storage.now(), updated=storage.now(), label=payload.get("label"))
    return storage.get("runs", rid)


def _repeats(sha: str, subsystem: str | None, sheet: str | None) -> list[dict]:
    if not subsystem:
        return []
    key = jobs.repeat_key(sha, subsystem, registry.versions(subsystem), sheet)
    return storage.select("SELECT r.id, r.run_id, r.created FROM results r WHERE r.repeat_key=? ORDER BY r.created DESC LIMIT 3", (key,))


def _register(run: dict, original: str, path: Path, sha: str, size: int, source: str) -> dict:
    rec = registry.validate_upload(registry.recognize(path, original),path)
    sub = rec.get("subsystem") if rec["path"] in ("recognized",) else None
    if run["subsystem"] and rec.get("subsystem") and rec["subsystem"] != run["subsystem"]:
        rec["conflict"] = f"Recognised as {rec['subsystem']} but this analysis is for {run['subsystem']}."
    fid = storage.new_id("file")
    status = {"recognized": "ready", "needs_confirmation": "awaiting_input", "exploration": "exploration_only",
              "unreadable": "unreadable"}[rec["path"]]
    if rec.get("needs"):
        status = "awaiting_input"
    storage.insert("files", id=fid, run_id=run["id"], original_name=original, sha256=sha, size=size,
                   stored_path=str(path), source_kind=source, subsystem=sub, recognition=rec, sheet=None,
                   status=status, error=None, created=storage.now())
    f = storage.get("files", fid)
    f["repeats"] = _repeats(sha, sub, None)
    return f


def _safe_name(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip() or "upload"
    return base[:200]


@router.post("/runs/{run_id}/files")
async def upload_files(run_id: str, files: list[UploadFile] = File(...)):
    run = _run_or_404(run_id)
    if run["state"] not in ("draft",):
        err(409, "run_frozen", "Files can only be added before analysis starts.")
    out, total = [], 0
    for up in files:
        original = _safe_name(up.filename or "upload")
        dest_dir = storage.run_dir(run_id) / "inputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{storage.new_id('in')}{Path(original).suffix.lower()[:8]}"
        h, size = hashlib.sha256(), 0
        try:
            with open(dest, "wb") as fh:
                while True:
                    chunk = await up.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE:
                        raise ValueError(f"{original} is larger than the {MAX_FILE // (1 << 20)} MiB per-file limit.")
                    if total > MAX_BATCH:
                        raise ValueError(f"The batch exceeds the {MAX_BATCH // (1 << 20)} MiB limit. "
                                         "For large Rail batches use 'Add a local folder'.")
                    h.update(chunk)
                    fh.write(chunk)
        except ValueError as e:
            dest.unlink(missing_ok=True)
            err(413, "too_large", str(e), "Use local-folder ingest for large batches.")
        if size == 0:
            dest.unlink(missing_ok=True)
            out.append({"original_name": original, "status": "unreadable",
                        "recognition": {"path": "unreadable", "reason": "The file is empty.", "suggestion":"Upload a recording containing sensor samples; a blank file cannot be analysed."}})
            continue
        out.append(_register(run, original, dest, h.hexdigest(), size, "upload"))
    storage.update("runs", run_id, updated=storage.now())
    return {"files": out}


def _readable(p: Path) -> bool:
    return LOCAL_PATHS == "any" or p.resolve().is_relative_to(DATASET_ROOT.resolve())


@router.post("/runs/{run_id}/local-path")
def add_local_path(run_id: str, payload: dict = Body(...)):
    """Reference files on local disk without copying them (the Rail test batch is 1.2 GB)."""
    run = _run_or_404(run_id)
    if run["state"] != "draft":
        err(409, "run_frozen", "Files can only be added before analysis starts.")
    p = Path(str(payload.get("path", ""))).expanduser()
    if not _readable(p):
        err(403, "path_not_allowed", "This server only reads files from its provided dataset folder.",
            "Upload the recording instead.", "path")
    if not p.exists():
        err(400, "path_not_found", f"Path not found: {p}", "Enter a file or folder path on this computer.", "path")
    if p.is_dir():
        cands = sorted([x for x in p.iterdir() if x.is_file() and x.suffix.lower() in (".csv", ".xlsx") and _readable(x)],
                       key=lambda x: (len(x.stem), x.stem))
        if not cands:
            err(400, "no_supported_files", "The folder has no .csv or .xlsx files.", field="path")
    else:
        cands = [p]
    if len(cands) > 500:
        err(400, "too_many_files", f"{len(cands)} files found; the limit is 500 per analysis.")
    out = []
    for f in cands:
        out.append(_register(run, f.name, f.resolve(), sha256_file(f), f.stat().st_size, "local_path"))
    storage.update("runs", run_id, updated=storage.now())
    return {"files": out}


@router.delete("/runs/{run_id}/files/{file_id}")
def remove_file(run_id: str, file_id: str):
    run = _run_or_404(run_id)
    f = storage.get("files", file_id)
    if f is None or f["run_id"] != run_id:
        err(404, "file_not_found", "File not in this analysis.")
    if run["state"] != "draft":
        err(409, "run_frozen", "Files cannot be removed after analysis starts.")
    if f["source_kind"] == "upload":
        Path(f["stored_path"]).unlink(missing_ok=True)
    with storage.conn() as c:
        c.execute("DELETE FROM files WHERE id=?", (file_id,))
    return {"removed": file_id}


@router.patch("/runs/{run_id}/interpretation")
def interpret(run_id: str, payload: dict = Body(...)):
    run = _run_or_404(run_id)
    if run["state"] != "draft":
        err(409, "run_frozen", "Interpretation is fixed once analysis starts.")
    f = storage.get("files", payload.get("file_id", ""))
    if f is None or f["run_id"] != run_id:
        err(404, "file_not_found", "File not in this analysis.", field="file_id")
    upd = {}
    rec = f["recognition"] or {}
    if "subsystem" in payload:
        s = payload["subsystem"]
        if s not in SUBSYSTEM_LABELS:
            err(400, "unknown_subsystem", f"Unknown subsystem {s!r}.", field="subsystem")
        # user confirmation states intent; the parser still has to accept the file
        try:
            registry.parsed(s, Path(f["stored_path"]), payload.get("sheet") or f["sheet"])
        except ParseError as e:
            err(422, e.code, f"Cannot interpret this file as {SUBSYSTEM_LABELS[s]}: {e.message}", e.suggestion, "subsystem")
        upd["subsystem"] = s
        rec = {**rec, "confirmed_by_user": s}
    if "sheet" in payload:
        sheets = [x["sheet"] for x in rec.get("sheets", [])]
        if payload["sheet"] not in sheets:
            err(400, "unknown_sheet", "That sheet is not in the workbook.", field="sheet")
        upd["sheet"] = payload["sheet"]
        rec = {**rec, "confirmed_sheet": payload["sheet"]}
    rec.pop("needs", None)
    rec["subsystem"]=upd.get("subsystem",f["subsystem"])
    rec["path"]="recognized"
    rec=registry.validate_upload(rec,Path(f["stored_path"]),upd.get("sheet",f["sheet"]))
    if rec["path"]=="unreadable":
        err(422,rec.get("code","invalid_file"),rec["reason"],rec["suggestion"])
    upd["recognition"] = rec
    upd["status"] = "ready"
    storage.update("files", f["id"], **upd)
    out = storage.get("files", f["id"])
    out["repeats"] = _repeats(out["sha256"], out["subsystem"], out["sheet"])
    return out


@router.post("/runs/{run_id}/analyze")
def analyze(run_id: str, payload: dict = Body(default={})):
    run = _run_or_404(run_id)
    key = payload.get("idempotency_key")
    if run["state"] != "draft":
        if key and run.get("idempotency_key") == key:
            kids = storage.select("SELECT id FROM runs WHERE parent_id=? OR id=?", (run_id, run_id))
            return {"runs": [k["id"] for k in kids], "duplicate_request": True}
        err(409, "already_started", "This analysis has already started.")
    files = storage.select("SELECT * FROM files WHERE run_id=?", (run_id,))
    ready = [f for f in files if f["status"] == "ready" and f["subsystem"]]
    pending = [f["original_name"] for f in files if f["status"] == "awaiting_input"]
    if pending:
        err(409, "awaiting_input", "Some files need a quick answer before analysis: " + ", ".join(pending[:5]))
    if not ready:
        err(400, "nothing_to_analyze", "No file is ready for prediction.",
            "Remove unsupported files or choose the subsystem for a recognised file.")
    groups: dict[str, list[dict]] = {}
    for f in ready:
        groups.setdefault(f["subsystem"], []).append(f)
    run_ids = []
    for k, (sub, fs) in enumerate(sorted(groups.items())):
        if k == 0:
            rid = run_id
            storage.update("runs", rid, subsystem=sub, state="queued", idempotency_key=key, files_total=len(fs),
                           updated=storage.now(), versions=registry.versions(sub))
        else:
            rid = storage.new_id("run")
            storage.insert("runs", id=rid, subsystem=sub, purpose=run["purpose"], state="queued", created=storage.now(),
                           updated=storage.now(), files_total=len(fs), parent_id=run_id, idempotency_key=key,
                           versions=registry.versions(sub), label=run.get("label"))
            for f in fs:
                storage.update("files", f["id"], run_id=rid)
        run_ids.append(rid)
    # Queue only after every group's files have moved to their own run: the worker picks up a queued run at once and
    # analyses all ready files still attached to it, so queueing inside the loop let the first run take the others' files.
    for rid in run_ids:
        jobs.enqueue(rid)
    return {"runs": run_ids, "excluded": [{"file": f["original_name"], "status": f["status"],
                                             "reason": (f["recognition"] or {}).get("reason")} for f in files if f not in ready]}


def _run_view(run: dict) -> dict:
    files = storage.select("SELECT * FROM files WHERE run_id=? ORDER BY created, original_name", (run["id"],))
    results = storage.select("SELECT id, file_id, available, headline, review_count, quality_state, model_version, repeat_of, created "
                             "FROM results WHERE run_id=?", (run["id"],))
    byfile = {r["file_id"]: r for r in results}
    for f in files:
        f["result"] = byfile.get(f["id"])
        if f["source_kind"] == "upload":
            f.pop("stored_path", None)
    kids = storage.select("SELECT id, subsystem, state FROM runs WHERE parent_id=?", (run["id"],))
    return {**run, "files": files, "siblings": kids,
            "review_total": sum(r["review_count"] or 0 for r in results),
            "subsystem_label": SUBSYSTEM_LABELS.get(run["subsystem"] or "", "Not yet recognised")}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    return _run_view(_run_or_404(run_id))


@router.get("/runs")
def list_runs(limit: int = Query(50, le=200), offset: int = 0, subsystem: str | None = None):
    q = "SELECT * FROM runs WHERE state <> 'draft'"
    args: list = []
    if subsystem:
        q += " AND subsystem=?"
        args.append(subsystem)
    q += " ORDER BY created DESC LIMIT ? OFFSET ?"
    runs = storage.select(q, (*args, limit, offset))
    out = []
    for r in runs:
        files = storage.select("SELECT original_name FROM files WHERE run_id=? ORDER BY original_name", (r["id"],))
        res = storage.select("SELECT review_count, quality_state, available FROM results WHERE run_id=?", (r["id"],))
        rev = storage.select("SELECT result_id, item_id, assessment FROM reviews WHERE kind='review' AND result_id IN "
                             "(SELECT id FROM results WHERE run_id=?) ORDER BY revision", (r["id"],))
        reviewed = {(x["result_id"], x["item_id"]) for x in rev if x["assessment"] not in ("leave_for_later", "note")}
        names = [f["original_name"] for f in files]
        out.append({**r, "file_names": names[:3], "file_count": len(names),
                    "review_total": sum(x["review_count"] or 0 for x in res), "reviewed_items": len(reviewed),
                    "quality": sorted({x["quality_state"] for x in res if x["quality_state"]}),
                    "subsystem_label": SUBSYSTEM_LABELS.get(r["subsystem"] or "", "—")})
    return {"runs": out}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str):
    run = _run_or_404(run_id)
    if run["state"] in ("queued", "running"):
        storage.update("runs", run_id, cancel_requested=1, updated=storage.now())
        if run["state"] == "queued":
            storage.update("runs", run_id, state="cancelled")
    return _run_view(storage.get("runs", run_id))


@router.post("/runs/{run_id}/retry")
def retry(run_id: str):
    run = _run_or_404(run_id)
    if run["state"] not in ("interrupted", "failed", "partial_failure", "cancelled"):
        err(409, "not_retryable", f"A {run['state']} analysis cannot be retried.")
    for f in storage.select("SELECT id FROM files WHERE run_id=? AND status='failed'", (run_id,)):
        storage.update("files", f["id"], status="ready", error=None)
    storage.update("runs", run_id, state="queued", cancel_requested=0, error=None, updated=storage.now())
    jobs.enqueue(run_id)
    return _run_view(storage.get("runs", run_id))


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    run = _run_or_404(run_id)
    if run["state"] in ("queued", "running"):
        err(409, "run_active", "Cancel the analysis before deleting it.")
    res = storage.select("SELECT id FROM results WHERE run_id=?", (run_id,))
    with storage.conn() as c:
        for r in res:
            c.execute("DELETE FROM reviews WHERE result_id=?", (r["id"],))
        c.execute("DELETE FROM results WHERE run_id=?", (run_id,))
        c.execute("DELETE FROM files WHERE run_id=?", (run_id,))
        c.execute("DELETE FROM runs WHERE id=?", (run_id,))
    shutil.rmtree(storage.STORE / "runs" / run_id, ignore_errors=True)  # never touches local-path sources
    return {"deleted": run_id}


# ---------------------------------------------------------------- results

@router.get("/samples/{subsystem}")
def download_sample(subsystem: str):
    if subsystem not in SUBSYSTEM_LABELS:
        err(404,"unknown_subsystem","No sample for that subsystem.")
    paths = exports.official_test_paths().get(subsystem, [])
    if not paths:
        err(503,"sample_unavailable","The provided official test dataset is not available locally.",
            "Restore the organizer's dataset folder or upload an official test input you received. No synthetic substitute is generated.")
    p = paths[0]
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if p.suffix == ".xlsx" else "text/csv"
    return FileResponse(p, media_type=media, filename=p.name, headers={"X-Sentinel-Source": "official-test-input"})


@router.get("/results/{rid}/diagnostic-charts")
def diagnostic_charts(rid: str):
    from diagnostics import diagnostic_charts as charts
    from diagnostics.model_store import load_model
    r=_result_or_404(rid)
    f=storage.get("files",r["file_id"])
    try:
        data=registry.parsed(r["subsystem"],Path(f["stored_path"]),f["sheet"])
        payload=storage.read_payload(r)
        model=load_model(r["subsystem"])
        if "diagnosis" not in payload:
            payload["diagnosis"]=registry.recommendations.build(r["subsystem"],data,payload,model)
        return {"charts":finite(charts.build(r["subsystem"],data,payload,model,f["original_name"]))}
    except ParseError as e:
        err(422,e.code,e.message,e.suggestion)
    except FileNotFoundError:
        err(410,"source_missing","The original recording is no longer available.","Upload the recording again to regenerate its evidence.")
    except ModelUnavailable as e:
        err(503,"model_unavailable",str(e),"Restore the frozen model bundle before regenerating charts; saved predictions have not been changed.")


@router.get("/results/{rid}/findings.csv")
def findings_csv(rid: str):
    full=get_result(rid)
    d=full["payload"].get("diagnosis")
    if not d:
        err(409,"legacy_result","This older result has no evidence-ranked findings.","Re-run the original recording with the current diagnostic policy.")
    stream=io.StringIO()
    w=csv.writer(stream)
    w.writerow(["file","subsystem","condition","rank","action","urgency","evidence_confidence_0_to_1","confidence_basis","signal","value","unit","time_or_sample_window","reference","confidence_note"])
    for rank,a in enumerate([d["primary"],*d["alternatives"]],1):
        for ev in a["evidence"]:
            row=[full["file"]["original_name"],full["subsystem"],d["condition"],rank,a["instruction"],a["urgency"],a["confidence"],a["confidence_basis"],ev["signal"],ev["value"],ev["unit"],ev["window"],ev.get("reference") or "",d["confidence_note"]]
            w.writerow([("'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v) for v in row])
    return Response(stream.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=findings.csv"})

@router.get("/runs/{run_id}/results")
def run_results(run_id: str, limit: int = Query(100, le=500), offset: int = 0):
    _run_or_404(run_id)
    rows = storage.select("SELECT * FROM results WHERE run_id=? ORDER BY created LIMIT ? OFFSET ?", (run_id, limit, offset))
    latest: dict[str, dict[str, str]] = {}
    for rv in storage.select("SELECT result_id, item_id, assessment FROM reviews WHERE kind='review' AND result_id IN "
                             "(SELECT id FROM results WHERE run_id=?) ORDER BY revision", (run_id,)):
        latest.setdefault(rv["result_id"], {})[rv["item_id"]] = rv["assessment"]
    status_latest: dict[str, dict[str, str]] = {}
    for rv in storage.select("SELECT result_id, item_id, assessment FROM reviews WHERE kind='status' AND result_id IN "
                             "(SELECT id FROM results WHERE run_id=?) ORDER BY revision", (run_id,)):
        status_latest.setdefault(rv["result_id"], {})[rv["item_id"]] = rv["assessment"]
    files = {f["id"]: f for f in storage.select("SELECT id, original_name, sha256, size FROM files WHERE run_id=?", (run_id,))}
    pol = _policy()
    out = []
    for r in rows:
        p = storage.read_payload(r)
        items = p.get("items", [])
        cards = [triage.card_for(r["subsystem"], i, p, pol) for i in items]
        slim = [{**{k: v for k, v in i.items() if k not in ("side_summary", "direction_votes", "daily_leaders", "top_cycle_ranges")},
                 "triage": c} for i, c in zip(items, cards)]
        out.append({"id": r["id"], "file": files.get(r["file_id"]), "available": bool(r["available"]),
                    "headline": r["headline"], "review_count": r["review_count"], "quality_state": r["quality_state"],
                    "model_version": r["model_version"], "repeat_of": r["repeat_of"], "items": slim,
                    "assessments": latest.get(r["id"], {}), "statuses": status_latest.get(r["id"], {}),
                    "operator_summary": triage.stream_summary(r["subsystem"], items, cards, pol),
                    "summary": p.get("summary"), "issues": p.get("issues", [])})
    return {"results": out, "offset": offset, "limit": limit}


def _reviews(rid: str) -> list[dict]:
    return storage.select("SELECT * FROM reviews WHERE result_id=? ORDER BY created, revision", (rid,))


@router.get("/results/{rid}")
def get_result(rid: str):
    r = _result_or_404(rid)
    f = storage.get("files", r["file_id"])
    payload = storage.read_payload(r)
    pol = _policy()
    for it in payload.get("items", []):
        it["triage"] = triage.card_for(r["subsystem"], it, payload, pol)
    run = storage.get("runs", r["run_id"]) or {}
    return {"id": rid, "run_id": r["run_id"], "subsystem": r["subsystem"], "repeat_of": r["repeat_of"],
            "file": {k: f[k] for k in ("id", "original_name", "sha256", "size", "sheet", "source_kind")},
            "asset_label": run.get("label"), "payload": payload, "reviews": _reviews(rid), "created": r["created"]}


@router.get("/results/{rid}/evidence")
def get_evidence(rid: str, item: str | None = None, view: str = "default", car: str | None = None,
                 pos: int | None = None, kind: str | None = None, t0: float | None = None, t1: float | None = None,
                 i0: int | None = None, i1: int | None = None, compare: str | None = None):
    r = _result_or_404(rid)
    f = storage.get("files", r["file_id"])
    payload = storage.read_payload(r)
    params = {k: v for k, v in dict(car=car, pos=pos, kind=kind, t0=t0, t1=t1, i0=i0, i1=i1, compare=compare).items()
              if v is not None}
    try:
        charts = registry.evidence(r["subsystem"], Path(f["stored_path"]), payload, item, view, params,
                                   f["original_name"], f["sheet"])
    except ModelUnavailable as e:
        err(503, "missing_model", str(e))
    except KeyError as e:
        err(404, "item_not_found", f"Unknown item {e}.")
    except FileNotFoundError:
        err(410, "source_missing", "The source file is no longer available at its recorded location.")
    return {"charts": finite(charts)}


def _review_common(rid: str, payload: dict) -> tuple[dict, str]:
    r = _result_or_404(rid)
    item = payload.get("item_id")
    items = {i["id"] for i in storage.read_payload(r).get("items", [])}
    if item not in items:
        err(400, "item_not_found", "Unknown finding for this result.", field="item_id")
    return r, item


@router.put("/results/{rid}/review")
def put_review(rid: str, payload: dict = Body(...)):
    _, item = _review_common(rid, payload)
    a = payload.get("assessment")
    if a not in ASSESSMENTS:
        err(400, "invalid_assessment", f"Assessment must be one of {sorted(ASSESSMENTS)}.", field="assessment")
    note = (payload.get("note") or "")[:4000]
    try:
        rec = storage.add_review(rid, item, "review", payload.get("expected_revision"), assessment=a, note=note,
                                 reviewer=(payload.get("reviewer") or "")[:120] or None, reason=None)
    except ValueError as e:
        err(409, "revision_conflict", str(e), "Reload to see the latest assessment, then try again.")
    return {"saved": True, "review": rec}


@router.put("/results/{rid}/priority")
def put_priority(rid: str, payload: dict = Body(...)):
    _, item = _review_common(rid, payload)
    level = payload.get("level")
    if level not in PRIORITIES:
        err(400, "invalid_priority", f"Priority must be one of {sorted(PRIORITIES)}.", field="level")
    reason = (payload.get("reason") or "").strip()
    assessor = (payload.get("assessor") or "").strip()
    if level != "unassessed" and (not reason or not assessor):
        err(400, "priority_needs_provenance", "A priority other than Unassessed needs the assessor's name and a reason.",
            "Enter who is assigning the priority and why (e.g. the operating policy that applies).", "reason")
    try:
        rec = storage.add_review(rid, item, "priority", payload.get("expected_revision"), assessment=level,
                                 note=None, reviewer=assessor[:120] or None, reason=reason[:2000] or None)
    except ValueError as e:
        err(409, "revision_conflict", str(e), "Reload and try again.")
    return {"saved": True, "priority": rec}


@router.put("/results/{rid}/status")
def put_status(rid: str, payload: dict = Body(...)):
    """Local investigation lifecycle: open → acknowledged → investigating → outcome → closed. Stored locally,
    append-only, never dispatched anywhere and never changes the prediction."""
    _, item = _review_common(rid, payload)
    st = payload.get("status")
    if st not in triage.STATUSES:
        err(400, "invalid_status", f"Status must be one of {list(triage.STATUSES)}.", field="status")
    who = (payload.get("assessor") or "").strip()[:120]
    if st != "open" and not who:
        err(400, "status_needs_name", "Say who is changing the investigation state.", "Enter your name or role.", "assessor")
    due = (payload.get("due") or "").strip()[:10] or None
    if due is not None:
        try:
            datetime.date.fromisoformat(due)
        except ValueError:
            err(400, "invalid_due", "Due date must be YYYY-MM-DD.", field="due")
    try:
        rec = storage.add_review(rid, item, "status", payload.get("expected_revision"), assessment=st,
                                 note=(payload.get("note") or "")[:4000] or None, reviewer=who or None, reason=None,
                                 assignee=(payload.get("assignee") or "").strip()[:120] or None, due=due)
    except ValueError as e:
        err(409, "revision_conflict", str(e), "Reload and try again.")
    return {"saved": True, "status": rec}


@router.get("/triage/policy")
def get_policy():
    return {"policy": _policy(), "defaults": triage.DEFAULT_POLICY}


@router.put("/triage/policy")
def put_policy(payload: dict = Body(...)):
    """Editable severity policy. Stored locally; a change re-ranks the Attention view but never changes predictions."""
    if payload.get("reset"):
        storage.set_setting(POLICY_KEY, None)
        return {"policy": _policy(), "saved": True}
    pol = payload.get("policy") or {}
    allowed = {"door", "acv", "rail", "shm"}
    clean: dict = {"edited": True, "edited_by": (payload.get("assessor") or "")[:120]}
    for k in allowed:
        if k in pol and isinstance(pol[k], dict):
            sect = {}
            for kk, vv in pol[k].items():
                if kk not in triage.DEFAULT_POLICY[k]:
                    err(400, "unknown_policy_key", f"Unknown policy key {k}.{kk}.", field=f"{k}.{kk}")
                default = triage.DEFAULT_POLICY[k][kk]
                if isinstance(default, str):
                    if vv not in triage.SEVERITIES:
                        err(400, "invalid_severity", f"{k}.{kk} must be one of {list(triage.SEVERITIES)}.", field=f"{k}.{kk}")
                else:
                    try:
                        vv = float(vv)
                    except (TypeError, ValueError):
                        err(400, "invalid_number", f"{k}.{kk} must be a number.", field=f"{k}.{kk}")
                sect[kk] = vv
            clean[k] = sect
    storage.set_setting(POLICY_KEY, clean)
    return {"policy": _policy(), "saved": True}


@router.get("/triage/reference")
def triage_reference():
    return {"severities": triage.SEVERITY_LABELS, "statuses": triage.STATUS_LABELS, "checklists": triage.CHECKLISTS,
            "maintenance_map": triage.MAINTENANCE_MAP}


@router.patch("/runs/{run_id}/label")
def set_label(run_id: str, payload: dict = Body(...)):
    """User-entered asset label (e.g. 'Train 123 · car 3 · door L2'). The data files carry no asset identity, so
    this is provenance typed by a person, shown as such, and used only to group findings."""
    _run_or_404(run_id)
    label = (payload.get("label") or "").strip()[:120] or None
    storage.update("runs", run_id, label=label, updated=storage.now())
    return {"id": run_id, "label": label}


@router.get("/attention")
def attention(include_closed: bool = False, include_info: bool = False):
    """Operator view: every finding from the newest analysis of each distinct input, as a triage card with its
    local investigation state, ranked by severity. Derived from stored results; nothing is live."""
    pol = _policy()
    rows = storage.select("SELECT r.*, ru.label AS asset_label, ru.created AS run_created, f.sha256 AS file_sha, f.original_name AS file_name "
                          "FROM results r JOIN runs ru ON ru.id = r.run_id JOIN files f ON f.id = r.file_id "
                          "WHERE ru.state IN ('completed','partial_failure') AND r.available = 1 ORDER BY r.created DESC, r.rowid DESC")
    seen: set[tuple] = set()
    cards = []
    for r in rows:
        key = (r["subsystem"], r["file_sha"])  # newest analysis of each distinct recording, whatever the model version
        if key in seen:
            continue
        seen.add(key)
        f = {"original_name": r["file_name"]}
        p = storage.read_payload(r)
        latest = _latest(storage.select("SELECT * FROM reviews WHERE result_id=? ORDER BY revision", (r["id"],)))
        for it in p.get("items", []):
            card = triage.card_for(r["subsystem"], it, p, pol)
            st = (latest.get("status", {}).get(it["id"]) or {}).get("assessment", "open")
            pr = latest.get("priority", {}).get(it["id"])
            if not include_info and card["severity"] == "info":
                continue
            if not include_closed and st in ("closed", "not_found"):
                continue
            st_row = latest.get("status", {}).get(it["id"]) or {}
            cards.append({"result_id": r["id"], "run_id": r["run_id"], "item_id": it["id"], "subsystem": r["subsystem"],
                          "file": f.get("original_name"), "asset_label": r["asset_label"], "analysed": r["created"],
                          "prediction": it.get("prediction") if not isinstance(it.get("prediction"), float) else round(it["prediction"], 4),
                          "status": st, "status_label": triage.STATUS_LABELS.get(st, st),
                          "assignee": st_row.get("assignee"), "due": st_row.get("due"), "status_by": st_row.get("reviewer"),
                          "priority": (pr or {}).get("assessment", "unassessed"), "priority_by": (pr or {}).get("reviewer"),
                          "priority_reason": (pr or {}).get("reason"),
                          "last_note": (latest.get("status", {}).get(it["id"]) or {}).get("note"),
                          "recording_context": p.get("recording_context"), **card})
    order = {s: i for i, s in enumerate(triage.SEVERITIES)}
    prio_order = {"urgent_assessment": 0, "planned_review": 1, "unassessed": 2}
    # person-entered priority first, then severity tier, then the strongest evidence within the tier, then newest
    cards.sort(key=lambda c: (prio_order.get(c["priority"], 2), order[c["severity"]], -float(c.get("strength") or 0.0), c["analysed"]))
    counts = {s: sum(1 for c in cards if c["severity"] == s) for s in triage.SEVERITIES}
    status_counts = {s: sum(1 for c in cards if c["status"] == s) for s in triage.STATUSES}
    return {"cards": cards, "counts": counts, "status_counts": status_counts, "policy": {k: pol[k] for k in ("version", "illustrative", "note")},
            "distinct_inputs": len(seen), "note": "Findings come from stored analyses of historical recordings; nothing here is live and no asset is verified."}


@router.get("/attention.csv")
def attention_csv(include_closed: bool = False, include_info: bool = False):
    """The open-findings list as a CSV for a shift hand-over. Same rows as /attention; not an official bundle file."""
    feed = attention(include_closed=include_closed, include_info=include_info)
    cols = ["severity", "severity_label", "subsystem", "asset_label", "file", "what", "where", "how_sure", "action", "next_check",
            "status_label", "assignee", "due", "priority", "priority_by", "analysed", "run_id", "item_id"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for c in feed["cards"]:
        w.writerow({k: ("" if c.get(k) is None else c.get(k)) for k in cols})
    return Response(buf.getvalue().encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=sentinel_open_findings_{datetime.date.today().isoformat()}.csv"})


@router.get("/files/{file_id}/explore")
def explore(file_id: str):
    """Descriptive charts for exploration-only files; no prediction, no inherited units."""
    f = storage.get("files", file_id)
    if f is None:
        err(404, "file_not_found", "Unknown file.")
    p = Path(f["stored_path"])
    try:
        if p.suffix.lower() == ".xlsx":
            df = pd.read_excel(p, nrows=200_000, engine="openpyxl")
        else:
            df = pd.read_csv(p, nrows=200_000, encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        err(422, "unreadable", f"Could not read the file: {e}")
    num = df.select_dtypes("number")
    charts = []
    for c in list(num.columns)[:6]:
        y = num[c].to_numpy(dtype=float)
        charts.append(chart(str(c), str(c), "", "Row index (no validated time axis)", f["original_name"],
                            [{"name": str(c), "role": "primary", **minmax_downsample(np.arange(len(y)), y)}]))
    return finite({"file": f["original_name"], "rows": len(df), "columns": [str(c) for c in df.columns[:60]],
                   "numeric_columns": len(num.columns), "charts": charts,
                   "missing_requirement": (f["recognition"] or {}).get("suggestion") or (f["recognition"] or {}).get("reason")})


# ---------------------------------------------------------------- exports

def _export(kind: str, data: bytes, filename: str, media: str, manifest: dict, run_ids: list[str]) -> dict:
    eid = storage.new_id("exp")
    path = storage.STORE / "exports" / eid / filename
    exports.write_bytes(path, data)
    storage.insert("exports", id=eid, kind=kind, created=storage.now(), path=str(path), filename=filename,
                   media_type=media, manifest=manifest, errors=None, run_ids=run_ids)
    return {"id": eid, "filename": filename, "download": f"/api/v1/exports/{eid}", "manifest": manifest}


def _run_results(run_id: str) -> list[tuple[dict, dict, dict]]:
    rows = storage.select("SELECT * FROM results WHERE run_id=? ORDER BY created", (run_id,))
    return [(r, storage.get("files", r["file_id"]), storage.read_payload(r)) for r in rows]


def _prediction_csv(run_id: str, result_id: str | None = None) -> tuple[bytes, str, dict]:
    """One analysis in the official *_predictions.csv format, through the serializer predictions.zip and the CLI use."""
    run = _run_or_404(run_id)
    if run["state"] not in ("completed", "partial_failure"):
        err(409, "not_complete", "The analysis has not finished.")
    rr = _run_results(run["id"])
    if result_id:
        rr = [x for x in rr if x[0]["id"] == result_id]
    missing = [f["original_name"] for f in storage.select("SELECT * FROM files WHERE run_id=? AND status IN ('ready','failed')", (run["id"],))]
    unavailable = [f["original_name"] for r, f, p in rr if not p.get("available", True)]
    if unavailable:
        err(409, "prediction_unavailable", "No prediction exists for: " + ", ".join(unavailable),
            "Resolve the listed files or export a partial analysis report instead.")
    sub = run["subsystem"]
    if sub == "door" and len(rr) > 1:
        err(409, "door_multiple_streams", "Door predictions have no file_id, so each stream is downloaded separately.",
            "Choose one stream's Prediction CSV.")
    res = [(f["original_name"], p) for r, f, p in rr]
    rows = exports.rows_for(sub, res)
    errs = exports.validate_rows(sub, rows, res)
    if errs:
        err(422, "export_invalid", "; ".join(errs))
    data = exports.to_csv_bytes(sub, rows)
    manifest = {"run_id": run["id"], "result_ids": [r["id"] for r, _, _ in rr], "rows": len(rows),
                "complete": not missing, "missing_files": missing, "serializer": exports.SERIALIZER_VERSION,
                "sha256": hashlib.sha256(data).hexdigest(), "model_versions": sorted({r["model_version"] or "" for r, _, _ in rr})}
    name = exports.CSV_NAMES[sub] if not missing else exports.CSV_NAMES[sub].replace(".csv", "_PARTIAL.csv")
    return data, name, manifest


@router.get("/runs/{run_id}/predictions.csv")
def prediction_csv(run_id: str):
    data, name, _ = _prediction_csv(run_id)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})


@router.post("/exports")
def create_export(payload: dict = Body(...)):
    kind = payload.get("kind")
    if kind == "csv":
        data, name, manifest = _prediction_csv(payload.get("run_id", ""), payload.get("result_id"))
        return _export("csv", data, name, "text/csv", manifest, [manifest["run_id"]])
    if kind == "report":
        run = _run_or_404(payload.get("run_id", ""))
        rr = _run_results(run["id"])
        files = storage.select("SELECT * FROM files WHERE run_id=?", (run["id"],))
        results = [{"id": r["id"], "file_id": r["file_id"], "payload": p} for r, f, p in rr]
        reviews = {r["id"]: _reviews(r["id"]) for r, _, _ in rr}
        html_ = exports.html_report(run, files, results, reviews)
        manifest = {"run_id": run["id"], "review_revisions": sum(len(v) for v in reviews.values()),
                    "complete": not any(f["status"] in ("ready", "failed") for f in files)}
        return _export("report", html_.encode("utf-8"), f"sentinel_report_{run['subsystem']}_{run['id']}.html",
                       "text/html", manifest, [run["id"]])
    if kind == "brief":
        r = _result_or_404(payload.get("result_id", ""))
        item_id = payload.get("item_id")
        p = storage.read_payload(r)
        item = next((i for i in p.get("items", []) if i["id"] == item_id), None)
        if item is None:
            err(404, "item_not_found", "Unknown finding for this result.", field="item_id")
        run = storage.get("runs", r["run_id"])
        f = storage.get("files", r["file_id"])
        card = triage.card_for(r["subsystem"], item, p, _policy())
        try:
            charts = registry.evidence(r["subsystem"], Path(f["stored_path"]), p, item_id if r["subsystem"] == "door" else None, "default",
                                       {"car": item.get("leading_car")} if r["subsystem"] == "acv" else {}, f["original_name"], f["sheet"])
        except (ModelUnavailable, FileNotFoundError, KeyError):
            charts = []
        html_ = exports.brief_html(run, f, p, item, card, _reviews(r["id"]), charts)
        manifest = {"run_id": r["run_id"], "result_id": r["id"], "item_id": item_id, "severity": card["severity"]}
        return _export("brief", html_.encode("utf-8"), f"sentinel_brief_{r['subsystem']}_{item_id}_{r['id']}.html", "text/html", manifest, [r["run_id"]])
    if kind == "bundle":
        sel = payload.get("runs") or {}
        selected, run_ids, source_hashes = {}, [], {}
        for sub, rid in sel.items():
            if not rid:
                continue
            run = _run_or_404(rid)
            if run["subsystem"] != sub:
                err(400, "wrong_subsystem", f"Run {rid} is a {run['subsystem']} analysis, not {sub}.")
            if run["state"] not in ("completed", "partial_failure"):
                err(409, "not_complete", f"The {sub} analysis has not completed.")
            rr = _run_results(rid)
            failed = [f["original_name"] for f in storage.select("SELECT * FROM files WHERE run_id=? AND status IN ('ready','failed')", (rid,))]
            if failed:
                err(409, "incomplete_task", f"{sub}: files without results: {failed[:10]}")
            selected[sub] = [(f["original_name"], p) for _, f, p in rr]
            source_hashes[sub] = {f["original_name"]: f["sha256"] for _, f, _ in rr}
            run_ids.append(rid)
        if not selected:
            err(400, "empty_selection", "Select at least one completed analysis.")
        try:
            blob, manifest = exports.build_bundle(selected, source_hashes)
        except exports.ExportError as e:
            raise HTTPException(422, {"code": "bundle_invalid", "message": "The bundle cannot be built.",
                                      "errors": e.errors, "recoverable": True})
        manifest["runs"] = sel
        manifest["model_versions"] = {s: storage.get("runs", r)["versions"] for s, r in sel.items() if r}
        return _export("bundle", blob, "predictions.zip", "application/zip", manifest, run_ids)
    err(400, "unknown_export", "kind must be csv, report, brief or bundle.")


@router.get("/exports")
def list_exports(limit: int = 20):
    return {"exports": storage.select("SELECT id, kind, created, filename, manifest FROM exports ORDER BY created DESC LIMIT ?", (limit,))}


@router.get("/exports/{eid}")
def download_export(eid: str):
    e = storage.get("exports", eid)
    if e is None or not e["path"] or not Path(e["path"]).exists():
        err(404, "export_not_found", "Export not found.")
    return FileResponse(e["path"], media_type=e["media_type"], filename=e["filename"])


@router.get("/exports/{eid}/info")
def export_info(eid: str):
    e = storage.get("exports", eid)
    if e is None:
        err(404, "export_not_found", "Export not found.")
    return e


@router.get("/prediction_exports/inventory")
def bundle_inventory():
    inv = exports.official_test_hashes()
    latest = {}
    for s in ("door", "acv", "rail", "shm"):
        runs = storage.select("SELECT id, created, state, files_total FROM runs WHERE subsystem=? AND state IN ('completed','partial_failure') "
                              "ORDER BY created DESC", (s,))
        eligible = []
        for r in runs:
            files = storage.select("SELECT original_name, sha256, status FROM files WHERE run_id=?", (r["id"],))
            names = [f["original_name"] for f in files]
            r["file_names"] = names[:4]
            r["file_count"] = len(names)
            exp = inv.get(s)
            r["matches_official_test"] = not exports.official_source_errors(s, names, {f["original_name"]: f["sha256"] for f in files}, exp or {})
            if r["state"] == "completed" and r["matches_official_test"] and all(f["status"] == "analyzed" for f in files):
                eligible.append(r)
        latest[s] = eligible[:10]
    return {"expected": {s: len(v) for s, v in inv.items()}, "candidates": latest}


# ---------------------------------------------------------------- methods

@router.get("/learn")
def learn():
    """Reference numbers for the Learn page, read from the frozen bundles so the explanations can never drift
    from what the models actually use."""
    out: dict = {}
    for t in ("door", "acv", "rail", "shm"):
        try:
            m = registry.load_model(t)
        except ModelUnavailable:
            out[t] = None
            continue
        if t == "door":
            out[t] = {"class_ranges": m["class_ranges"], "class_counts": m["class_counts"], "cutoffs": m["cutoffs"],
                      "relative_rule": m.get("relative_rule"), "gap_threshold_s": m["segmentation"]["gap_threshold_s"],
                      "reference_n": {k: v["n"] for k, v in m.get("reference", {}).items()}, "version": m["version"]}
        elif t == "acv":
            out[t] = {"params": m["params"], "cooling_modes": m["cooling_modes"], "score_definition": m["score_definition"], "version": m["version"]}
        elif t == "rail":
            out[t] = {"normal_side_rms_median": m["reference"]["normal_side_rms_median"], "threshold": m["stage1_threshold"],
                      "review_band": m["review"]["stage1_band"], "bands_hz": m["bands_hz"], "side_established": m["side_policy"]["established"],
                      "n_features": {"stage1": len(m["stage1_features"]), "stage2": len(m["stage2_features"])}, "version": m["version"]}
        else:
            val = REPO_ROOT / "reports" / "validation" / "shm.json"
            tgt = load_json(val).get("target") if val.exists() else None
            out[t] = {"feature_ranges": m["feature_ranges"], "gate": m["gate"], "m": m["selected"].get("m"), "formula": m["selected"].get("formula"),
                      "validation": m["validation"]["selected"], "training_damage": tgt, "version": m["version"]}
    return {"reference": out, "maintenance_map": triage.MAINTENANCE_MAP, "checklists": triage.CHECKLISTS}


@router.get("/methods")
def methods():
    val = REPO_ROOT / "reports" / "validation"
    p = val / "summary.json"
    fc = val / "forecast_acv.json"
    forecast = None
    if fc.exists():
        f = load_json(fc)
        forecast = {k: f[k] for k in ("target", "inputs_at_origin", "protocol", "baseline", "promotion_rule", "promoted")}
        forecast["horizons"] = {h: {k: v[k] for k in ("mae_ridge_mean_K", "mae_persistence_mean_K", "mean_improvement",
                                                     "cases_improved", "n_cases")} for h, v in f["horizons"].items()}
    man = val / "split_manifest.json"
    splits = None
    if man.exists():
        m = load_json(man)
        splits = {"door": f"{len(m['door']['folds'])} contiguous time blocks of labelled cycles",
                  "acv": f"leave-one-case-out over {len(m['acv']['cases'])} cases",
                  "rail": m["rail"]["scheme"], "shm": m["shm"]["scheme"],
                  "duplicates": m.get("duplicate_training_files"), "created": m["created"]}
    return {"summary": load_json(p) if p.exists() else None, "forecast": forecast, "splits": splits,
            "subsystems": registry.subsystem_catalog()}


@router.get("/methods/{subsystem}")
def method(subsystem: str):
    if subsystem not in SUBSYSTEM_LABELS:
        err(404, "unknown_subsystem", "Unknown subsystem.")
    card = ARTIFACT_DIR / subsystem / "MODEL_CARD.md"
    val = REPO_ROOT / "reports" / "validation" / f"{subsystem}.json"
    v = load_json(val) if val.exists() else None
    if v:  # drop bulky arrays
        v.pop("files", None)
        v.pop("truth", None)
        for c in (v.get("candidates") or {}).values():
            if isinstance(c, dict):
                c.pop("predictions", None)
                c.pop("fold_choices", None)
        if subsystem == "door":
            for s in (v.get("cutoff_sensitivity") or {}).values():
                s["curve"] = s["curve"][::4]
        if subsystem == "rail":
            v["reference"] = None
    return {"subsystem": subsystem, "label": SUBSYSTEM_LABELS[subsystem],
            "model_card": card.read_text(encoding="utf-8") if card.exists() else None, "validation": finite(v)}
