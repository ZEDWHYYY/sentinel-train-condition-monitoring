"""Seeded sensor fixtures, no predictions/labels inferred from held-out data.

SHM 'faulty' is a high-stress challenge, not a labelled structural fault.
Rail spectra are mechanistic synthetic signals, not real-world validation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "command-center/backend"))
from diagnostics.door import COLUMNS

SEED = 20260919
SUBSYSTEMS = ("door", "acv", "rail", "shm")
CASES = ("healthy", "faulty", "borderline", "missing_column", "extra_columns", "wrong_scale",
         "gaps", "duplicate_timestamps", "outliers", "single_row", "empty", "large", "wrong_subsystem")


def door_frame(kind="healthy", n=3200):
    rng = np.random.default_rng(SEED)
    idx = np.arange(n)
    cycle, step = idx // 160, idx % 160
    opening = cycle % 2 == 0
    t = pd.Timestamp("2026-01-01") + pd.to_timedelta(cycle * 15 + step * .02, unit="s")
    stamp = [f"{v.year}-{v.month}-{v.day}-{v.hour}-{v.minute}-{v.second}-{v.microsecond // 1000}" for v in t]
    cur = 540 + 60*np.sin(np.pi*step/160)**2 + rng.normal(0, 8, n)
    if kind == "faulty":
        cur *= 1.85
    if kind == "borderline":
        cur *= np.where(cycle % 5 == 0, 1.13, 1.0)
    # Position increases while opening in the supplied controller convention.
    position = np.where(opening, step/159*1000, 1000-step/159*1000)
    close_switch = np.where(opening, step < 8, step > 150).astype(int)
    arr = {"Datetime":stamp, COLUMNS[1]:cur, COLUMNS[2]:480, COLUMNS[3]:120,
           COLUMNS[4]:32, COLUMNS[5]:32, "Close command":(~opening).astype(int),
           "Open command":opening.astype(int), "DCSR":close_switch, "DCSL":close_switch,
           "DLSR":close_switch, "DLSL":close_switch, "Door Opened":(opening & (step>150)).astype(int),
           "Door Locked":((~opening)&(step>150)).astype(int), "Door is opening":opening.astype(int),
           "Door is closing":(~opening).astype(int), COLUMNS[-1]:position}
    return pd.DataFrame(arr)[COLUMNS]


def acv_frame(kind="healthy", n=360):
    rng = np.random.default_rng(SEED+1)
    arr = {"Car Model":["synthetic"]*n, "Train Number":["test"]*n,
           "Time":pd.date_range("2026-01-01",periods=n,freq="30s")}
    common = .15*np.sin(np.arange(n)/25)
    for c in range(1,9):
        offset = 3.0 if kind=="faulty" and c==3 else (.45 if kind=="borderline" and c in (3,4) else 0)
        prefix = f"Car {c:02d} - "
        arr.update({prefix+"ACV Setting Mode":"Automatic", prefix+"ACV Running Mode":"Automatic Cooling",
                    prefix+"ACV Control Temperature (Cooling)":23., prefix+"ACV Control Temperature (Heating)":20.,
                    prefix+"Indoor Average Temperature":23.2+common+offset+rng.normal(0,.08,n),
                    prefix+"Outdoor Average Temperature":32.+common, prefix+"ACV Load Halved":"No",
                    prefix+"ACV Information Valid":"Valid"})
    return pd.DataFrame(arr)


def rail_frame(kind="healthy", n=10000):
    rng = np.random.default_rng(SEED+2)
    t = np.arange(n)/10000
    arr = {"Rotating speed":((np.arange(n)//12)%2).astype(int)}
    for car in range(1,9):
        for p in range(1,9):
            for k in ("Vibration","Shock"):
                base = .07 if k=="Vibration" else .4
                sig = base*rng.normal(size=n)+base*.4*np.sin(2*np.pi*70*t+car)
                if kind in ("faulty","borderline"):
                    amplitude = (2.4 if kind=="faulty" else .22)*(1. if p%2 else .55)
                    sig += amplitude*np.sin(2*np.pi*(620+car*12)*t+p)
                arr[f"{k} of bearing in position {p} of car {car}"] = sig
    return pd.DataFrame(arr)


def shm_frame(kind="healthy", n=12000):
    rng = np.random.default_rng(SEED+3)
    t = np.arange(n)
    amp = {"healthy":12.,"borderline":28.,"faulty":100.}[kind]
    # Periodic loading plus smaller broadband stress; all raw units undocumented.
    return pd.DataFrame({"stress":amp*np.sin(2*np.pi*t/500)+.8*rng.normal(size=n)})


MAKERS = {"door":door_frame,"acv":acv_frame,"rail":rail_frame,"shm":shm_frame}


def generate(output=ROOT/"tests/fixtures", samples_only=False):
    output = Path(output)
    manifest = []
    for sub in SUBSYSTEMS:
        dest = output/sub
        dest.mkdir(parents=True,exist_ok=True)
        healthy = MAKERS[sub]()
        for case in (["healthy"] if samples_only else CASES):
            df = MAKERS[sub](case) if case in ("healthy","faulty","borderline") else healthy.copy()
            header = sub != "shm"
            if case == "large":
                df = MAKERS[sub](n=100000 if sub!="door" else 100160)
            elif case == "missing_column":
                missing = {"door":COLUMNS[1],"acv":"Time","rail":"Vibration of bearing in position 1 of car 1","shm":"stress"}[sub]
                df = df.drop(columns=[missing])
                if sub=="shm":
                    df = pd.DataFrame({"Timestamp":pd.date_range("2026-01-01",periods=100,freq="s"),"note":"stress missing"})
                    header = True
            elif case == "extra_columns":
                df["Operator note"] = "synthetic auxiliary column"
                header = True
            elif case == "wrong_scale":
                if sub=="door":
                    df[COLUMNS[1]] /= 1000  # A written in an mA field
                elif sub=="acv":
                    for c in df:
                        if "Temperature" in c: df[c] += 273.15
                elif sub=="rail":
                    df.iloc[:,1:] *= 1e6
                else:
                    df["stress"] *= 1e6
            elif case == "gaps":
                cols = [COLUMNS[1]] if sub=="door" else ([c for c in df if "Indoor Average" in c] if sub=="acv" else list(df.columns)[1:5] if sub=="rail" else ["stress"])
                df.loc[40:49,cols] = np.nan
            elif case == "duplicate_timestamps":
                if sub in ("rail","shm"):
                    df["Timestamp"] = np.arange(len(df))
                    header = True
                col = "Datetime" if sub=="door" else "Time" if sub=="acv" else "Timestamp"
                df.loc[1,col] = df.loc[0,col]
            elif case == "outliers":
                col = COLUMNS[1] if sub=="door" else "Car 03 - Indoor Average Temperature" if sub=="acv" else df.columns[1] if sub=="rail" else "stress"
                df.loc[len(df)//2,col] = 1e12
            elif case == "single_row":
                df = df.iloc[:1]
            elif case == "empty":
                (dest/f"{case}.csv").write_bytes(b"")
                manifest.append({"subsystem":sub,"case":case,"file":f"{sub}/{case}.csv","rows":0,"seed":SEED})
                continue
            elif case == "wrong_subsystem":
                other = "acv" if sub=="door" else "door"
                df = MAKERS[other]()
                header = True
            path = dest/f"{case}.csv"
            df.to_csv(path,index=False,header=header,float_format="%.6g")
            manifest.append({"subsystem":sub,"case":case,"file":f"{sub}/{case}.csv","rows":len(df),"bytes":path.stat().st_size,"seed":SEED,
                             "note":"SHM high stress, not labelled structural fault" if sub=="shm" else "Synthetic challenge; not held-out validation"})
        if sub=="acv":
            healthy.to_excel(dest/"healthy.xlsx",index=False)
            manifest.append({"subsystem":sub,"case":"healthy_workbook","file":"acv/healthy.xlsx","rows":len(healthy),"seed":SEED})
    if not samples_only:
        (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(f"Generated {len(manifest)} reproducible fixtures in {output}",flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=ROOT/"tests/fixtures")
    ap.add_argument("--samples-only",action="store_true",help="Generate small software-test fixtures only; never used by the app or bundle export")
    args=ap.parse_args()
    generate(args.output,args.samples_only)
