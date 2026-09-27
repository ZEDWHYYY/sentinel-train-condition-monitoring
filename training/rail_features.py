"""Extract and cache full-resolution Rail channel features for Train and Test.

Cache key = file SHA-256 + FEATURE_VERSION, so renamed files reuse features
and a feature change invalidates the cache. Source files are only read.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "command-center" / "backend"))

from diagnostics import rail  # noqa: E402
from diagnostics.common import CACHE_DIR, DATASET_ROOT, FEATURE_VERSION, sha256_file  # noqa: E402

RAIL_DIR = DATASET_ROOT / "Rail_Corrugation"


def cache_path(sha: str) -> Path:
    return CACHE_DIR / "rail" / FEATURE_VERSION / f"{sha}.npz"


def extract(path: Path) -> dict:
    sha = sha256_file(path)
    cp = cache_path(sha)
    if cp.exists():
        z = np.load(cp)
        return {"file": path.name, "sha": sha, "ch": z["ch"], "transitions": int(z["tr"]), "rows": int(z["rows"])}
    d = rail.parse(path)
    ch = rail.channel_features(d)
    sp = rail.speed_pulse(d)
    cp.parent.mkdir(parents=True, exist_ok=True)
    tr = -1 if sp["transitions"] is None else sp["transitions"]
    np.savez(cp, ch=ch, tr=tr, rows=d.data.shape[0])
    return {"file": path.name, "sha": sha, "ch": ch, "transitions": tr, "rows": d.data.shape[0]}


def extract_all(split: str, workers: int = 8) -> list[dict]:
    files = sorted((RAIL_DIR / split).glob("*.csv"), key=lambda p: int("".join(ch for ch in p.stem if ch.isdigit())))
    shas = {p: sha256_file(p) for p in files}
    missing = [p for p in files if not cache_path(shas[p]).exists()]
    if missing:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            list(ex.map(extract, missing, chunksize=4))
    return [extract(p) for p in files]


if __name__ == "__main__":
    for split in ("Train", "Test"):
        t = time.time()
        res = extract_all(split)
        print(f"{split}: {len(res)} files in {time.time() - t:.1f}s")
