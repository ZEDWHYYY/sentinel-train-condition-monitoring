"""Re-run the provided held-out batches through a running app and verify the saved ZIP.

Creates four real analyses and a downloadable export in that app's history. Does
not replace the existing bundle, change models or generate synthetic data.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
COUNTS = {"door": 1, "acv": 1, "rail": 68, "shm": 16}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    started = time.perf_counter()
    with httpx.Client(base_url=args.api_url, timeout=180) as client:
        def request(method, url, **kwargs):
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()

        datasets = {d["subsystem"]: d for d in request("GET", "/api/v1/datasets")["datasets"] if not d["training_example"]}
        assert set(datasets) == set(COUNTS), "All four official test folders must be available"
        selected = {}
        for sub, expected in COUNTS.items():
            d = datasets[sub]
            assert d["files"] == expected, (sub, d["files"], expected)
            rid = request("POST", "/api/v1/runs", json={"subsystem": sub})["id"]
            uploaded = request("POST", f"/api/v1/runs/{rid}/local-path", json={"path": d["path"]})["files"]
            assert len(uploaded) == expected and all(f["status"] == "ready" for f in uploaded)
            request("POST", f"/api/v1/runs/{rid}/analyze", json={})
            deadline = time.monotonic() + 300
            while True:
                run = request("GET", f"/api/v1/runs/{rid}")
                if run["state"] not in ("running", "queued"):
                    break
                assert time.monotonic() < deadline, f"{sub}: analysis timed out"
                time.sleep(.25)
            assert run["state"] == "completed", run
            selected[sub] = rid
            print(f"{sub}: {expected} official inputs analysed", flush=True)

        exported = request("POST", "/api/v1/exports", json={"kind": "bundle", "runs": selected})
        download = client.get(exported["download"])
        download.raise_for_status()
        coverage = exported["manifest"]["coverage"]
        assert {s: len(v["source_files"]) for s, v in coverage.items()} == COUNTS
        assert all(v["source_verification"] == "filename_and_sha256" for v in coverage.values())
        checks = {}
        with zipfile.ZipFile(io.BytesIO(download.content)) as current, zipfile.ZipFile(ROOT / "prediction_exports/predictions.zip") as saved, tempfile.TemporaryDirectory(prefix="ps3-bundle-parity-") as tmp:
            assert sorted(current.namelist()) == sorted(f"{s}_predictions.csv" for s in COUNTS)
            assert sorted(current.namelist()) == sorted(saved.namelist())
            for sub in COUNTS:
                name = f"{sub}_predictions.csv"
                data = current.read(name)
                assert data == saved.read(name), f"{name}: predictions changed from the saved bundle"
                output = Path(tmp) / name
                subprocess.run([sys.executable, str(ROOT / "command-center/backend/predict.py"), "--task", sub,
                                "--input", datasets[sub]["path"], "--output", str(output)], check=True, cwd=ROOT)
                assert data == output.read_bytes(), f"{name}: app/CLI mismatch"
                checks[sub] = {"status": "pass", "inputs": COUNTS[sub], "prediction_rows": coverage[sub]["rows"],
                               "sha256": hashlib.sha256(data).hexdigest(), "matches_existing_archive": True,
                               "matches_cli": True, "source_files": coverage[sub]["source_files"]}
        report = {"status": "pass", "official_inputs": sum(COUNTS.values()), "archive": "prediction_exports/predictions.zip",
                  "no_synthetic_or_training_inputs": True, "checks": checks, "app_export": exported,
                  "seconds": round(time.perf_counter() - started, 3)}
        (ROOT / "reports/prediction_export_verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"PASS: {sum(COUNTS.values())} official inputs; four CSVs identical to saved bundle and CLI.")


if __name__ == "__main__":
    main()
