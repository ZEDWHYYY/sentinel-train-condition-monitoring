"""Read every organizer data/example file; optionally run every sensor recording.

Outputs are evidence, never inputs to model selection. Organizer files stay read-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "command-center/backend"))

import pandas as pd
from diagnostics import registry
from diagnostics.common import DATASET_ROOT, finite, sha256_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", action="store_true")
    ap.add_argument("--output", default="reports/sample_inventory.json")
    args = ap.parse_args()
    records = []
    start = time.perf_counter()
    for path in sorted((DATASET_ROOT.parent).rglob("*")):
        if path.suffix.lower() not in (".csv", ".xlsx", ".txt"):
            continue
        record = {"file": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
                  "sha256": sha256_file(path)}
        sub = {"Door": "door", "ACV": "acv", "Rail_Corrugation": "rail", "SHM": "shm"}.get(path.relative_to(DATASET_ROOT.parent).parts[1])
        sensor = "02_Datasets" in path.parts and "Labels" not in path.name and "Answer" not in path.name
        try:
            if sensor and sub:
                data = registry.parsed(sub, path)
                record.update(subsystem=sub, profile=registry.profile_of(sub, data),
                              issues=[x.to_dict() for x in data.issues])
                if path.suffix == ".xlsx":
                    with pd.ExcelFile(path) as xl:
                        record["sheets"] = [{"name": s, "columns": list(pd.read_excel(xl, sheet_name=s, nrows=0).columns)} for s in xl.sheet_names]
                elif sub == "shm":
                    record["columns"] = ["stress (headerless)"]
                else:
                    with path.open(encoding="utf-8-sig") as f:
                        record["columns"] = next(csv.reader(f))
                if args.pipeline:
                    tick = time.perf_counter()
                    res = registry.analyze_file(sub, path, path.name)
                    record["output"] = {k: res.get(k) for k in ("available", "headline", "summary", "model_version", "diagnosis")}
                    record["predictions"] = [{k: i.get(k) for k in ("id", "prediction", "start_time", "end_time", "ranked_cars", "decision", "review_reasons") if k in i} for i in res["items"]]
                    record["analysis_seconds"] = round(time.perf_counter() - tick, 4)
                registry._parsed.cache_clear()
            else:
                frame = pd.read_csv(path)
                record.update(kind="labels_or_illustrative_output", rows=len(frame), columns=list(frame.columns), preview=frame.head(5).to_dict("records"))
            record["status"] = "pass"
        except Exception as exc:
            record.update(status="fail", error=f"{type(exc).__name__}: {exc}")
        records.append(record)
        if len(records) % 40 == 0:
            print(f"Read {len(records)} files", flush=True)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(finite({"files": records, "seconds": time.perf_counter() - start}), indent=2), encoding="utf-8")
    print(json.dumps({"files": len(records), "failures": [r for r in records if r["status"] != "pass"], "output": str(output)}))


if __name__ == "__main__":
    main()
