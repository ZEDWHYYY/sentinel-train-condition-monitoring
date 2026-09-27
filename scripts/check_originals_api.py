"""Exercise all 429 organizer recordings through the real API/worker/chart/export path.

Local-path ingest avoids copying 6 GB; inputs are never modified. Results live in
a fresh temporary store. Frozen predictions must match the pre-change audit.
"""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "command-center/backend"))


def signature(items):
    return [{k: i[k] for k in ("prediction", "ranked_cars", "start_time", "end_time") if k in i} for i in items]


def main():
    before = json.loads((ROOT / "tests/baselines/samples_before.json").read_text())["files"]
    samples = [x for x in before if "predictions" in x]
    assert len(samples) == 429, "Expected the complete audited original inventory"
    records = []
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ps3-original-api-") as store:
        os.environ["SENTINEL_STORE"] = store
        from fastapi.testclient import TestClient
        import main as api
        logging.getLogger("httpx").setLevel(logging.WARNING)
        from diagnostics import registry
        with TestClient(api.app) as client:
            for sample in samples:
                tick = time.perf_counter()
                record = {"file": sample["file"], "subsystem": sample["subsystem"]}
                try:
                    path = ROOT / sample["file"]
                    assert path.is_file(), f"Organizer source is missing: {path}"
                    r = client.post("/api/v1/runs", json={"subsystem": sample["subsystem"]})
                    assert r.status_code == 200, r.text
                    rid = r.json()["id"]
                    up = client.post(f"/api/v1/runs/{rid}/local-path", json={"path": str(path)})
                    assert up.status_code == 200, up.text
                    f = up.json()["files"][0]
                    assert f["status"] == "ready", f
                    begun = client.post(f"/api/v1/runs/{rid}/analyze", json={})
                    assert begun.status_code == 200, begun.text
                    deadline = time.monotonic() + 120
                    while True:
                        run = client.get(f"/api/v1/runs/{rid}").json()
                        if run["state"] not in ("running", "queued"):
                            break
                        assert time.monotonic() < deadline, "Analysis timed out"
                        time.sleep(.02)
                    assert run["state"] == "completed", run
                    rows = client.get(f"/api/v1/runs/{rid}/results").json()["results"]
                    assert len(rows) == 1
                    result = client.get(f"/api/v1/results/{rows[0]['id']}").json()["payload"]
                    assert result["available"] and result["diagnosis"]
                    assert signature(result["items"]) == signature(sample["predictions"]), "Frozen prediction changed"
                    chart = client.get(f"/api/v1/results/{rows[0]['id']}/diagnostic-charts")
                    assert chart.status_code == 200, chart.text
                    charts = chart.json()["charts"]
                    assert len(charts) >= 2 and all(c["unit"] and c["series"] for c in charts)
                    csv = client.get(f"/api/v1/results/{rows[0]['id']}/findings.csv")
                    assert csv.status_code == 200 and "confidence_basis" in csv.text
                    record.update(status="pass", predictions=signature(result["items"]), diagnosis=result["diagnosis"],
                                  chart_ids=[c["id"] for c in charts], csv_bytes=len(csv.content),
                                  rows=result["profile"]["rows"], model=result["model_version"], seconds=round(time.perf_counter()-tick, 4))
                except Exception as exc:
                    record.update(status="fail", error=f"{type(exc).__name__}: {exc}")
                records.append(record)
                registry._parsed.cache_clear()
                if len(records) % 25 == 0:
                    print(f"API + charts + CSV: {len(records)}/{len(samples)}", flush=True)
    report = {"files": records, "seconds": round(time.perf_counter()-start, 3), "failures": sum(r["status"] != "pass" for r in records)}
    (ROOT / "reports/originals_api.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{len(records)} recordings; {report['failures']} failures; {report['seconds']} seconds")
    if report["failures"]:
        print(json.dumps([r for r in records if r["status"] == "fail"], indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
