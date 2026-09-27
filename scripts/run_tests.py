"""One honest full-suite entry point. Requires `make setup` once.

No mocks of predictions, no source-data mutation, no test storage in run_store.
Writes executed phase timings and individual case outcomes even on failure.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "command-center/frontend"
PY = sys.executable
REPORTS = ROOT / "reports"


def main():
    phases = []
    started = time.perf_counter()
    env = {**os.environ, "SENTINEL_API_ORIGIN": "http://127.0.0.1:8018", "NEXT_DIST_DIR": ".next-engineering", "NEXT_TELEMETRY_DISABLED": "1", "NEXT_PUBLIC_API_BASE": ""}
    commands = [
        ("Seeded fixture generation", [PY, "scripts/generate_test_data.py"], ROOT),
        ("Backend / unit / API / CLI parity", [PY, "-m", "pytest", "command-center/backend/tests", "-q", "--junitxml=reports/tests_backend.xml"], ROOT),
        ("All original files / pipeline inventory", [PY, "scripts/audit_samples.py", "--pipeline", "--output", "reports/samples_after.json"], ROOT),
        ("All 429 originals: API, worker, charts, CSV, baseline parity", [PY, "scripts/check_originals_api.py"], ROOT),
        ("Synthetic outcome ledger", [PY, "scripts/check_fixtures.py", "reports/fixtures_after.json"], ROOT),
        ("Production build / strict types", ["npm", "run", "build"], WEB),
        ("Browser workflows / accessibility / responsive layouts", ["npx", "playwright", "test"], WEB),
        ("Dependency security audit", ["npm", "audit", "--audit-level=moderate"], WEB),
    ]
    try:
        for name, command, cwd in commands:
            print(f"\n{name}", flush=True)
            tick = time.perf_counter()
            run = subprocess.run(command, cwd=cwd, env=env)
            phases.append({"phase": name, "status": "pass" if run.returncode == 0 else "fail", "seconds": round(time.perf_counter()-tick, 3), "command": command})
            if run.returncode:
                raise SystemExit(run.returncode)
    finally:
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "full_suite.json").write_text(json.dumps({"phases": phases, "seconds": round(time.perf_counter()-started, 3)}, indent=2) + "\n")
        lines = ["# Executed test cases", "", "Generated from JUnit reports by `make test`. Individual original-file checks are in `reports/originals_api.json`.", "", "| Suite | Test | Result | Seconds |", "|---|---|---|---|"]
        for xml in ("tests_backend.xml", "tests_browser.xml"):
            p = REPORTS / xml
            if not p.exists():
                continue
            for case in ET.parse(p).iter("testcase"):
                state = "FAIL" if case.find("failure") is not None or case.find("error") is not None else "SKIP" if case.find("skipped") is not None else "PASS"
                name = case.get("name", "").replace("|", "\\|")
                lines.append(f"| {xml} | {name} | {state} | {case.get('time', '')} |")
        (ROOT / "docs/TEST_CASES.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
