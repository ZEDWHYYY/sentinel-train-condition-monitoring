"""One bounded background worker. Files are processed sequentially; progress
reflects real stages; cancellation takes effect between files; a restart marks
unfinished runs as interrupted instead of claiming they finished."""
from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path

import storage
from diagnostics import registry
from diagnostics.common import ParseError, sha256_file

log = logging.getLogger("sentinel.jobs")
_q: "queue.Queue[str]" = queue.Queue()
_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    for r in storage.select("SELECT id FROM runs WHERE state IN ('queued','running','validating')"):
        storage.update("runs", r["id"], state="interrupted", stage=None, updated=storage.now(),
                       error={"code": "interrupted", "message": "The app stopped while this run was in progress. Re-run it to finish.",
                              "recoverable": True})
    threading.Thread(target=_loop, name="sentinel-worker", daemon=True).start()


def enqueue(run_id: str) -> None:
    _q.put(run_id)


def repeat_key(sha: str, subsystem: str, versions: dict, sheet: str | None) -> str:
    return "|".join([sha, subsystem, sheet or "", versions["parser"], versions["features"], str(versions["model"]), versions["policy"]])


def _loop() -> None:
    while True:
        run_id = _q.get()
        try:
            _process(run_id)
        except Exception as e:  # noqa: BLE001 - keep worker alive; failure is recorded visibly
            log.exception("run %s failed", run_id)
            storage.update("runs", run_id, state="failed", updated=storage.now(),
                           error={"code": "internal_failure", "message": str(e), "recoverable": True,
                                  "detail": traceback.format_exc()[-2000:]})


def _process(run_id: str) -> None:
    run = storage.get("runs", run_id)
    if run is None or run["state"] != "queued":
        return
    files = storage.select("SELECT * FROM files WHERE run_id=? AND status IN ('ready','analyzed') "
                           "ORDER BY created, original_name", (run_id,))
    subsystem = run["subsystem"]
    versions = registry.versions(subsystem)
    storage.update("runs", run_id, state="running", files_total=len(files), files_done=0, versions=versions,
                   updated=storage.now())
    failures = 0
    for k, f in enumerate(files):
        if storage.get("runs", run_id)["cancel_requested"]:
            storage.update("runs", run_id, state="cancelled", stage=None, updated=storage.now())
            return
        existing = storage.select("SELECT id FROM results WHERE run_id=? AND file_id=?", (run_id, f["id"]))
        if existing:
            continue

        def stage(s: str, _k=k, _f=f):
            storage.update("runs", run_id, stage=f"{s} — {_f['original_name']} ({_k + 1} of {len(files)})", updated=storage.now())

        path = Path(f["stored_path"])
        try:
            if f["source_kind"] == "local_path":
                stage("Checking file")
                if sha256_file(path) != f["sha256"]:
                    raise ParseError("source_changed", "The file on disk changed after it was added to this run.",
                                     "Add the file again to analyse its current contents.")
            payload = registry.analyze_file(subsystem, path, f["original_name"], f["sheet"], stage)
        except ParseError as e:
            failures += 1
            storage.update("files", f["id"], status="failed",
                           error={"code": e.code, "message": e.message, "suggestion": e.suggestion, "recoverable": True})
            storage.update("runs", run_id, files_done=k + 1, updated=storage.now())
            continue
        except Exception as e:  # noqa: BLE001
            failures += 1
            log.exception("file %s failed", f["id"])
            storage.update("files", f["id"], status="failed",
                           error={"code": "internal_failure", "message": f"Analysis failed: {e}", "recoverable": True})
            storage.update("runs", run_id, files_done=k + 1, updated=storage.now())
            continue
        rid = storage.new_id("res")
        rk = repeat_key(f["sha256"], subsystem, versions, f["sheet"])
        prior = storage.select("SELECT id FROM results WHERE repeat_key=? AND run_id<>? ORDER BY created LIMIT 1", (rk, run_id))
        payload["recording_context"] = {
            "asset": "Asset not linked", "asset_verified": False,
            "recording_interval": payload.get("profile", {}).get("coverage"),
            "timezone": "unknown", "uploaded": storage.now(), "freshness": "historical upload — not live condition",
        }
        p = storage.write_payload(run_id, rid, payload)
        n_review = sum(1 for i in payload.get("items", []) if i.get("review_reasons"))
        storage.insert("results", id=rid, run_id=run_id, file_id=f["id"], subsystem=subsystem,
                       available=1 if payload.get("available", True) else 0, payload_path=str(p),
                       headline=payload.get("headline"), review_count=n_review, quality_state=payload.get("quality_state"),
                       model_version=payload.get("model_version"), repeat_key=rk,
                       repeat_of=prior[0]["id"] if prior else None, created=storage.now())
        storage.update("files", f["id"], status="analyzed")
        storage.update("runs", run_id, files_done=k + 1, updated=storage.now())
    final = "completed" if failures == 0 else ("failed" if failures == len(files) else "partial_failure")
    storage.update("runs", run_id, state=final, stage=None, updated=storage.now())
