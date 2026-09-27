"""Strict official CSV serializers, bundle ZIP builder/validator and the
self-contained HTML analysis report."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import math
import re
import stat
import time
import zipfile
from functools import lru_cache
from pathlib import Path

from .common import DATASET_ROOT, SUBSYSTEM_LABELS, sha256_file
from .metrics import DOOR_LABELS, RAIL_LABELS

SERIALIZER_VERSION = "ps3-export-1.1.0"
CSV_NAMES = {"door": "door_predictions.csv", "acv": "acv_predictions.csv", "rail": "rail_predictions.csv",
             "shm": "shm_predictions.csv"}
HEADERS = {"door": ["start_time", "end_time", "prediction"], "acv": ["file_id", "ranked_cars"],
           "rail": ["file_id", "prediction"], "shm": ["file_id", "prediction"]}


class ExportError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def rows_for(subsystem: str, results: list[tuple[str, dict]]) -> list[dict]:
    """results: [(original file name, stored result payload)]; rows in natural file order."""
    results = sorted(results, key=lambda r: _natural(r[0]))
    rows: list[dict] = []
    for fid, r in results:
        if subsystem == "door":
            rows += [{"start_time": i["start_time"], "end_time": i["end_time"], "prediction": i["prediction"]}
                     for i in sorted(r["items"], key=lambda i: i["t0"])]
        elif subsystem == "acv":
            rows.append({"file_id": fid, "ranked_cars": "|".join(r["items"][0]["ranked_cars"])})
        elif subsystem == "rail":
            rows.append({"file_id": fid, "prediction": r["items"][0]["prediction"]})
        else:
            rows.append({"file_id": fid, "prediction": repr(float(r["items"][0]["prediction"]))})
    return rows


def validate_rows(subsystem: str, rows: list[dict], results: list[tuple[str, dict]] | None = None) -> list[str]:
    errs = []
    if not rows:
        errs.append(f"{subsystem}: no prediction rows.")
    for k, r in enumerate(rows, 1):
        if list(r.keys()) != HEADERS[subsystem]:
            errs.append(f"{subsystem} row {k}: wrong columns {list(r.keys())}")
            continue
        if subsystem == "door" and r["prediction"] not in DOOR_LABELS:
            errs.append(f"door row {k}: invalid label {r['prediction']!r}")
        if subsystem == "rail" and r["prediction"] not in RAIL_LABELS:
            errs.append(f"rail row {k}: invalid label {r['prediction']!r}")
        if subsystem == "shm":
            try:
                v = float(r["prediction"])
                if not math.isfinite(v) or v <= 0:
                    errs.append(f"shm row {k}: prediction must be finite and positive")
            except ValueError:
                errs.append(f"shm row {k}: prediction is not numeric")
    if subsystem != "door":
        ids = [r["file_id"] for r in rows]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            errs.append(f"{subsystem}: duplicate file_id(s) {dup} — resolve which analysis to export.")
    if subsystem == "acv" and results:
        for fid, res in results:
            cars = res["items"][0]["ranked_cars"]
            header_cars = res.get("profile", {}).get("extra", {}).get("cars", cars)
            if sorted(cars) != sorted(header_cars) or len(set(cars)) != len(cars):
                errs.append(f"acv {fid}: ranking must list every header car exactly once")
    return errs


def to_csv_bytes(subsystem: str, rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS[subsystem], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def official_test_paths() -> dict[str, list[Path]]:
    """Only the organiser's held-out input locations, never training or fixtures."""
    inv: dict[str, list[Path]] = {}
    base = DATASET_ROOT
    if (base / "Door" / "Test.csv").exists():
        inv["door"] = [base / "Door" / "Test.csv"]
    for s, sub, pat in (("acv", "ACV/Test", "*.xlsx"), ("rail", "Rail_Corrugation/Test", "*.csv"),
                        ("shm", "SHM/Test", "*.csv")):
        p = base / sub
        if p.exists():
            inv[s] = sorted((x for x in p.glob(pat) if x.is_file()), key=lambda x: _natural(x.name))
    return inv


def official_test_inventory() -> dict[str, list[str]]:
    return {s: [p.name for p in paths] for s, paths in official_test_paths().items()}


@lru_cache(maxsize=256)
def _source_digest(path: str, size: int, mtime_ns: int, ctime_ns: int) -> str:
    # Stat values invalidate cached hashes when the local reference changes.
    return sha256_file(path)


def official_test_hashes() -> dict[str, dict[str, str]]:
    out = {}
    for s, paths in official_test_paths().items():
        out[s] = {}
        for p in paths:
            st = p.stat()
            out[s][p.name] = _source_digest(str(p.resolve()), st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    return out


def official_source_errors(subsystem: str, names: list[str], source_hashes: dict[str, str],
                           expected: dict[str, str]) -> list[str]:
    """Fail closed: an official-looking filename is not proof of official content."""
    if not expected:
        return [f"{subsystem}: official test inputs are unavailable; restore the provided dataset folder before building a bundle."]
    errors = []
    missing = sorted(set(expected) - set(names))
    extra = sorted(set(names) - set(expected))
    if missing:
        errors.append(f"{subsystem}: missing official test file(s): {missing[:10]}")
    if extra:
        errors.append(f"{subsystem}: file(s) not in the official test set: {extra[:10]}")
    if len(names) != len(set(names)):
        errors.append(f"{subsystem}: duplicate source filenames; select one analysis of each official input.")
    mismatched = sorted(n for n in set(names) & set(expected) if source_hashes.get(n) != expected[n])
    if mismatched:
        errors.append(f"{subsystem}: content does not match the provided official test file(s): {mismatched[:10]}. Synthetic, training or modified files cannot be exported; analyse the official test batch.")
    return errors


def build_bundle(selected: dict[str, list[tuple[str, dict]]],
                     source_hashes: dict[str, dict[str, str]] | None = None) -> tuple[bytes, dict]:
    """selected: subsystem -> [(file_id, result)]. Returns (zip bytes, manifest)."""
    errors, coverage, files = [], {}, {}
    official = official_test_hashes()
    source_hashes = source_hashes or {}
    for s in ("door", "acv", "rail", "shm"):
        if s not in selected:
            coverage[s] = {"status": "excluded", "note": "Not included — this subsystem scores zero."}
            continue
        res = selected[s]
        unavailable = [fid for fid, r in res if not r.get("available", True)
                       or any(i.get("prediction") is None for i in r.get("items", []))]
        if unavailable:
            errors.append(f"{s}: prediction unavailable for {unavailable}")
            continue
        if s == "door" and len(res) != 1:
            errors.append("door: select exactly one Door stream (the official file has no file_id, so streams cannot be merged).")
            continue
        rows = rows_for(s, res)
        errs = validate_rows(s, rows, res)
        expected = official.get(s, {})
        exp = list(expected)
        got = [fid for fid, _ in res]
        missing = sorted(set(exp) - set(got))
        extra = sorted(set(got) - set(exp))
        errs += official_source_errors(s, got, source_hashes.get(s, {}), expected)
        errors += errs
        data = to_csv_bytes(s, rows)
        files[CSV_NAMES[s]] = data
        coverage[s] = {"status": "ok" if not errs else "error", "rows": len(rows), "expected": len(exp) if exp else None,
                       "missing": missing, "extra": extra, "sha256": hashlib.sha256(data).hexdigest(),
                       "source_verification": "filename_and_sha256", "source_files": expected}
    if errors:
        raise ExportError(errors)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            # Ordinary files readable by anyone (-rw-r--r--): a bare writestr() stores no file type and
            # owner-only 0600 permissions, which some upload checkers reject or cannot read after unzipping.
            info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, data)
    blob = buf.getvalue()
    check = validate_zip(blob)
    if check:
        raise ExportError(check)
    return blob, {"serializer": SERIALIZER_VERSION, "coverage": coverage, "zip_sha256": hashlib.sha256(blob).hexdigest(),
                  "members": sorted(files)}


def validate_zip(blob: bytes) -> list[str]:
    errs = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            if "/" in n or "\\" in n:
                errs.append(f"ZIP member {n} is not at the root")
            if n not in CSV_NAMES.values():
                errs.append(f"Unexpected ZIP member {n}")
    return errs


# ---------------------------------------------------------------- report

def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _svg(chart_: dict, w: int = 720, h: int = 180) -> str:
    """Tiny static rendering of a line/bar chart for the offline report."""
    series = chart_.get("series") or []
    pts = []
    for s in series[:3]:
        xs = s.get("x") or []
        ys = s.get("max") if s.get("max") is not None else s.get("y")
        if not xs or ys is None:
            continue
        pairs = [(float(a), float(b)) for a, b in zip(xs, ys) if a is not None and b is not None and not isinstance(a, str)]
        if pairs:
            pts.append((s.get("name", ""), pairs))
    if not pts:
        return ""
    allx = [p[0] for _, ps in pts for p in ps]
    ally = [p[1] for _, ps in pts for p in ps]
    x0, x1, y0, y1 = min(allx), max(allx), min(ally), max(ally)
    x1 = x1 if x1 > x0 else x0 + 1
    y1 = y1 if y1 > y0 else y0 + 1
    colors = ["#1f5fbf", "#8a8f98", "#c98a1a"]
    lines = []
    for k, (name, ps) in enumerate(pts):
        d = " ".join(f"{(a - x0) / (x1 - x0) * (w - 20) + 10:.1f},{h - 10 - (b - y0) / (y1 - y0) * (h - 20):.1f}" for a, b in ps[::max(1, len(ps) // 600)])
        lines.append(f'<polyline fill="none" stroke="{colors[k]}" stroke-width="1.2" points="{d}"/>')
    legend = " · ".join(f'<span style="color:{colors[k]}">■ {_e(n)}</span>' for k, (n, _) in enumerate(pts))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_e(chart_.get("title"))}" '
            f'style="background:#fafafa;border:1px solid #ddd">{"".join(lines)}</svg><div class="small">{legend} — '
            f'y range {y0:.4g} to {y1:.4g} {_e(chart_.get("unit"))}; x: {_e(chart_.get("x_label"))}</div>')


def html_report(run: dict, files: list[dict], results: list[dict], reviews: dict[str, list[dict]]) -> str:
    s = run["subsystem"]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>SENTINEL report — {_e(SUBSYSTEM_LABELS.get(s, s))}</title>",
             "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1b1f24}"
             "table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}"
             ".small{font-size:13px;color:#57606a}.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:13px;border:1px solid}"
             ".fault{color:#b42318;border-color:#b42318}.review{color:#9a6700;border-color:#9a6700}code{font-size:13px}</style></head><body>",
             f"<h1>SENTINEL analysis report — {_e(SUBSYSTEM_LABELS.get(s, s))}</h1>",
             f"<p class='small'>Run <code>{_e(run['id'])}</code> · created {_e(run['created'])} · "
             f"versions {_e(run.get('versions'))}</p>",
             "<p class='small'>Local diagnostic prototype. Predictions are frozen model output; analyst assessments are shown "
             "separately and never change the prediction. Not a certification of fitness for service.</p>"]
    fmap = {f["id"]: f for f in files}
    for r in results:
        f = fmap.get(r["file_id"], {})
        p = r["payload"]
        parts.append(f"<h2>{_e(f.get('original_name'))}</h2>")
        parts.append(f"<p class='small'>SHA-256 <code>{_e(f.get('sha256'))}</code> · {_e(f.get('size'))} bytes · "
                     f"model {_e(p.get('model_version'))} · data quality: {_e(p.get('quality_state'))} · "
                     "recording context: asset not linked; historical upload (freshness unknown)</p>")
        parts.append(f"<p><strong>{_e(p.get('headline'))}</strong></p>")
        if p.get("overview_chart"):
            parts.append(f"<h3>{_e(p['overview_chart'].get('title'))}</h3>{_svg(p['overview_chart'])}"
                         f"<p class='small'>{_e(p['overview_chart'].get('caption'))}</p>")
        items = p.get("items", [])
        if items:
            parts.append("<table><tr><th>Item</th><th>Prediction</th><th>Evidence</th><th>Review reasons and next check</th><th>Analyst assessment</th></tr>")
            for it in items:
                rv = [x for x in reviews.get(r["id"], []) if x.get("item_id") == it["id"]]
                last = rv[-1] if rv else None
                pred = it.get("prediction")
                if s == "acv":
                    pred = " | ".join(it["ranked_cars"])
                cls = "fault" if pred in ("Abnormal resistance", "Side I", "Side II") else ""
                reasons = "".join(f"<div><span class='tag review'>{_e(x['code'])}</span> {_e(x['message'])}<br>"
                                  f"<em>Next check:</em> {_e(x['next_check'])}</div>" for x in it.get("review_reasons", []))
                obs = "".join(f"<div>{_e(o)}</div>" for o in it.get("observations", []))
                assess = (f"{_e(last['assessment'])} (rev {last['revision']}, {_e(last['created'])})"
                          f"<div class='small'>{_e(last.get('note'))}</div>") if last else "unreviewed"
                parts.append(f"<tr><td>{_e(it['id'])}<div class='small'>{_e(it.get('start_time', ''))} {_e(it.get('end_time', ''))}</div></td>"
                             f"<td class='{cls}'>{_e(pred)}</td><td>{obs}</td><td>{reasons or 'No review trigger found'}</td><td>{assess}</td></tr>")
            parts.append("</table>")
        issues = p.get("issues", [])
        parts.append("<h3>Data quality</h3>" + ("<ul>" + "".join(
            f"<li><strong>{_e(i['code'])}</strong> ({_e(i['severity'])}): {_e(i['description'])} — {_e(i['treatment'])}</li>"
            for i in issues) + "</ul>" if issues else "<p>No checked issues found.</p>"))
    parts.append("<h3>Method limitations</h3><p class='small'>See the model card for this subsystem (Method and validation page). "
                 "Maintenance history is not connected; no MTBF/MTTR or remaining-life figures are produced.</p></body></html>")
    return "".join(parts)


def brief_html(run: dict, f: dict, payload: dict, item: dict, card: dict, reviews: list[dict], charts: list[dict]) -> str:
    """One-page maintenance hand-off for a single finding (Part 2). Printable, self-contained, and explicit about
    what is machine output, what is a person's entry, and what is not known (asset, live status)."""
    from .triage import CHECKLISTS, MAINTENANCE_MAP, SEVERITY_LABELS, STATUS_LABELS
    s = run["subsystem"]
    sev = card["severity"]
    colour = {"high": "#b42318", "medium": "#9a6700", "low": "#1f5fbf", "info": "#6b7280"}[sev]
    mine = [r for r in reviews if r.get("item_id") == item["id"]]
    status = next((r for r in reversed(mine) if r["kind"] == "status"), None)
    prio = next((r for r in reversed(mine) if r["kind"] == "priority"), None)
    notes = [r for r in mine if r["kind"] == "review" and r.get("note")]
    pred = " | ".join(item["ranked_cars"]) if s == "acv" else item.get("prediction")
    if isinstance(pred, float):
        pred = f"{pred:.4g}"
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>SENTINEL job brief — {_e(card['what'])}</title>",
             "<style>body{font:15px/1.45 system-ui,sans-serif;max-width:860px;margin:20px auto;padding:0 16px;color:#1b1f24}"
             "h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:18px 0 6px;border-bottom:1px solid #d0d7de}"
             ".sev{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-weight:700}"
             ".grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px}.k{color:#57606a;font-size:13px}"
             "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}"
             ".box{border:1px solid #d0d7de;border-radius:8px;padding:10px 12px;margin:8px 0}.small{font-size:12px;color:#57606a}"
             "ul{margin:4px 0 4px 18px}.sign{margin-top:14px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}.sign div{border-top:1px solid #1b1f24;padding-top:4px;font-size:12px}"
             "@media print{a{color:inherit;text-decoration:none}}</style></head><body>",
             f"<p class='small'>SENTINEL maintenance job brief · {_e(SUBSYSTEM_LABELS.get(s, s))} · generated from analysis <code>{_e(run['id'])}</code> · model <code>{_e(payload.get('model_version'))}</code></p>",
             f"<h1>{_e(card['what'])}</h1>",
             f"<p><span class='sev' style='background:{colour}'>{_e(SEVERITY_LABELS[sev])}</span> &nbsp; severity per policy <code>{_e(card.get('policy_version'))}</code>"
             + (" (illustrative defaults — not an operator standard)" if card.get("policy_illustrative") else " (edited locally)") + "</p>",
             "<div class='grid'>",
             f"<div><div class='k'>Where</div>{_e(card['where'])}</div>",
             f"<div><div class='k'>Asset</div>{_e(run.get('label') or 'Not linked — the data file carries no asset identity')}"
             + ("<span class='small'> (label typed by a user, not verified)</span>" if run.get("label") else "") + "</div>",
             f"<div><div class='k'>Recording</div>{_e(f.get('original_name'))} · {_e((payload.get('profile') or {}).get('coverage'))}</div>",
             f"<div><div class='k'>Freshness</div>Historical recording analysed {_e(run.get('created'))}; not a live condition</div>",
             f"<div><div class='k'>Machine prediction</div><strong>{_e(pred)}</strong>" + (f" <span class='small'>{_e(card.get('detail'))}</span>" if card.get("detail") else "") + "</div>",
             f"<div><div class='k'>Investigation state</div>{_e(STATUS_LABELS.get(status['assessment'], status['assessment']) if status else 'Open')}"
             + (f" <span class='small'>by {_e(status.get('reviewer'))}, {_e(status['created'])}</span>" if status else "") + "</div>",
             "</div>",
             f"<h2>How sure</h2><p>{_e(card['how_sure'])}</p>",
             f"<h2>Recommended action</h2><p><strong>{_e(card['action'])}</strong></p><p><em>Next check:</em> {_e(card['next_check'])}</p>"]
    if item.get("review_reasons"):
        parts.append("<h2>Why the analysis asks for review</h2><ul>" + "".join(
            f"<li>{_e(r['message'])} <span class='small'>Next check: {_e(r['next_check'])}</span></li>" for r in item["review_reasons"]) + "</ul>")
    if item.get("observations"):
        parts.append("<h2>Evidence (machine observations)</h2><ul>" + "".join(f"<li>{_e(o)}</li>" for o in item["observations"]) + "</ul>")
    for c in charts[:2]:
        svg = _svg(c, 760, 170)
        if svg:
            parts.append(f"<div class='box'><strong>{_e(c.get('title'))}</strong>{svg}<div class='small'>{_e(c.get('caption'))}</div></div>")
    parts.append("<h2>Suggested checklist</h2><ul>" + "".join(f"<li>☐ {_e(x)}</li>" for x in CHECKLISTS[s]) + "</ul>")
    mm = MAINTENANCE_MAP[s]
    parts.append(f"<h2>Maintenance decision this supports</h2><p>{_e(mm['decision'])} <span class='small'>(instead of: {_e(mm['instead_of'])}). "
                 "General condition-monitoring practice, not an LTA policy document.</span></p>")
    if prio or notes:
        parts.append("<h2>Entered by people</h2>")
        if prio:
            parts.append(f"<p>Priority: <strong>{_e(prio['assessment'])}</strong> — {_e(prio.get('reviewer'))}: {_e(prio.get('reason'))}</p>")
        for n in notes:
            parts.append(f"<p class='small'>{_e(n['created'])} · {_e(n.get('reviewer') or 'analyst')}: “{_e(n['note'])}”</p>")
    parts.append("<div class='sign'><div>Issued by / date</div><div>Technician / date</div><div>Outcome recorded in SENTINEL</div></div>")
    parts.append("<p class='small' style='margin-top:14px'>This brief is generated locally from a stored analysis. It does not dispatch work, "
                 "does not verify the asset, and does not certify fitness for service. Predictions are frozen model output; "
                 "everything under “Entered by people” was typed by a user.</p></body></html>")
    return "".join(parts)


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
