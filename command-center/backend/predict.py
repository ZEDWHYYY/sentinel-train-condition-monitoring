"""Same-pipeline command-line predictor (project CLI; the app remains the
official way to generate exported predictions).

    python predict.py --task shm  --input <file-or-directory> --output shm_predictions.csv
    python predict.py --task door --input Test.csv --output door_predictions.csv

--task may be omitted when every input is recognised as the same subsystem.
Uses exactly the parsers, frozen models and serializers the app uses.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagnostics import exports, registry  # noqa: E402
from diagnostics.common import ParseError  # noqa: E402


def collect(inp: Path) -> list[Path]:
    if inp.is_dir():
        files = [p for p in inp.iterdir() if p.suffix.lower() in (".csv", ".xlsx")]
        return sorted(files, key=lambda p: (len(p.stem), p.stem))
    return [inp]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--task", choices=["door", "acv", "rail", "shm"])
    ap.add_argument("--sheet", help="ACV sheet name when a workbook has several compatible sheets")
    a = ap.parse_args(argv)
    files = collect(a.input)
    if not files:
        print("No input files found.", file=sys.stderr)
        return 2
    task = a.task
    if task is None:
        subs = {registry.recognize(p, p.name).get("subsystem") for p in files}
        if len(subs) != 1 or None in subs:
            print(f"Could not recognise a single subsystem ({subs}); pass --task.", file=sys.stderr)
            return 2
        task = subs.pop()
    if task == "door" and len(files) != 1:
        print("Door output has no file_id: pass exactly one continuous stream.", file=sys.stderr)
        return 2
    results = []
    for p in files:
        try:
            r = registry.analyze_file(task, p, p.name, a.sheet)
        except ParseError as e:
            print(f"{p.name}: {e.message} {e.suggestion}", file=sys.stderr)
            return 1
        if not r.get("available", True):
            print(f"{p.name}: prediction unavailable — {r.get('unavailable_reason', '')}", file=sys.stderr)
            return 1
        results.append((p.name, r))
        print(f"{p.name}: {r['headline']}", file=sys.stderr)
    rows = exports.rows_for(task, results)
    errs = exports.validate_rows(task, rows, results)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(exports.to_csv_bytes(task, rows))
    print(f"wrote {len(rows)} rows to {a.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
