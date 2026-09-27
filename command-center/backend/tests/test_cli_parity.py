"""T40: the CLI produces byte-identical CSVs to the app export, and the results page's
"Download prediction CSV" reproduces the exported file exactly."""
import time
import zipfile

import pytest

import predict
from diagnostics.common import REPO_ROOT
from .conftest import requires_data


@requires_data
@pytest.mark.parametrize("task,rel", [("door", "Door/Test.csv"), ("acv", "ACV/Test"), ("shm", "SHM/Test"),
                                      ("rail", "Rail_Corrugation/Test")])
def test_cli_matches_app(client, data_root, tmp_path, task, rel):
    out = tmp_path / "cli.csv"
    assert predict.main(["--task", task, "--input", str(data_root / rel), "--output", str(out)]) == 0
    r = client.post("/api/v1/runs", json={}).json()
    client.post(f"/api/v1/runs/{r['id']}/local-path", json={"path": str(data_root / rel)})
    rid = client.post(f"/api/v1/runs/{r['id']}/analyze", json={}).json()["runs"][0]
    for _ in range(600):
        if client.get(f"/api/v1/runs/{rid}").json()["state"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    e = client.post("/api/v1/exports", json={"kind": "csv", "run_id": rid}).json()
    assert client.get(e["download"]).content == out.read_bytes()
    download = client.get(f"/api/v1/runs/{rid}/predictions.csv")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert f"filename={task}_predictions.csv" in download.headers["content-disposition"]
    assert download.content == out.read_bytes()
    with zipfile.ZipFile(REPO_ROOT / "prediction_exports" / "predictions.zip") as exported:
        assert download.content == exported.read(f"{task}_predictions.csv")
