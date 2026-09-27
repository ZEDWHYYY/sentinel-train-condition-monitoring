"""Shared types and helpers used by all four task pipelines, training and the app."""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]
ARTIFACT_DIR = Path(os.environ.get("SENTINEL_ARTIFACT_DIR", REPO_ROOT / "artifacts" / "ps3"))
DATASET_ROOT = Path(os.environ.get(
    "SENTINEL_DATASET_ROOT",
    REPO_ROOT / "NebulaX-Hackathon-ProblemStatement" / "PS3" / "02_Datasets"))
CACHE_DIR = Path(os.environ.get("SENTINEL_CACHE_DIR", REPO_ROOT / ".cache" / "ps3"))

PARSER_VERSION = "ps3-parsers-1.1.0"
FEATURE_VERSION = "ps3-features-1.0.0"

SUBSYSTEMS = ("door", "acv", "rail", "shm")
SUBSYSTEM_LABELS = {
    "door": "Door",
    "acv": "ACV (air conditioning)",
    "rail": "Rail corrugation",
    "shm": "Structural health (SHM)",
}


class ParseError(Exception):
    """A file cannot be read as the requested format; message is user-facing."""

    def __init__(self, code: str, message: str, suggestion: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion or "Check the required columns, units and sample count against the downloadable sample, then upload the corrected recording."


@dataclass
class QualityIssue:
    code: str
    severity: str  # info | warning | blocking
    description: str
    scope: str = "file"
    treatment: str = "Reported only; no data altered."
    effect: str = "None on prediction."
    next_step: str = ""
    rows: list[int] | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["rows"] is not None:
            d["rows"] = d["rows"][:50]
        return d


@dataclass
class ReviewReason:
    code: str
    message: str
    next_check: str
    evidence_ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Profile:
    rows: int
    columns: int
    sample_rate_hz: float | None
    sample_rate_source: str
    coverage: str
    channels: list[dict] = field(default_factory=list)
    missing_fraction: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def finite(x: Any) -> Any:
    """Recursively convert to JSON-safe values; non-finite floats become None."""
    if isinstance(x, dict):
        return {str(k): finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    if isinstance(x, np.ndarray):
        return finite(x.tolist())
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def minmax_downsample(x: np.ndarray, y: np.ndarray, max_points: int = 1500) -> dict:
    """Bucket min/max rendering so sharp peaks survive display downsampling.

    Returns bucket centres with min and max; each bucket also carries the index
    range so hover can report provenance. Features never use this output.
    """
    n = len(y)
    if n == 0:
        return {"x": [], "min": [], "max": [], "i0": [], "i1": [], "aggregated": False}
    if n <= max_points:
        idx = np.arange(n)
        return {"x": finite(x), "min": finite(y), "max": finite(y),
                "i0": idx.tolist(), "i1": idx.tolist(), "aggregated": False}
    buckets = max_points // 2
    edges = np.linspace(0, n, buckets + 1).astype(int)
    xs, mins, maxs, i0s, i1s = [], [], [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        valid = seg[np.isfinite(seg)]
        xs.append(float(x[a]))
        if len(valid):
            mins.append(float(valid.min()))
            maxs.append(float(valid.max()))
        else:
            mins.append(None)
            maxs.append(None)
        i0s.append(int(a))
        i1s.append(int(b - 1))
    return {"x": xs, "min": mins, "max": maxs, "i0": i0s, "i1": i1s, "aggregated": True}


def chart(title: str, signal: str, unit: str, x_label: str, source: str,
          series: list[dict], state: str = "raw", reference: str | None = None,
          markers: list[dict] | None = None, bands: list[dict] | None = None,
          caption: str = "", kind: str = "line") -> dict:
    """Chart contract: every chart declares what it shows and where from."""
    return finite({
        "kind": kind, "title": title, "signal": signal, "unit": unit or "unknown unit",
        "x_label": x_label, "source": source, "state": state, "reference": reference,
        "series": series, "markers": markers or [], "bands": bands or [], "caption": caption,
    })


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(finite(obj), f, ensure_ascii=False, separators=(",", ":"))  # compact: machine-read artifacts
    os.replace(tmp, path)
