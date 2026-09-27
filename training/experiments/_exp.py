"""Shared path setup for pre-registered experiments (see docs/EXPERIMENTS.md)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "command-center" / "backend"))
OUT = ROOT / "reports" / "validation" / "experiments"
OUT.mkdir(parents=True, exist_ok=True)
