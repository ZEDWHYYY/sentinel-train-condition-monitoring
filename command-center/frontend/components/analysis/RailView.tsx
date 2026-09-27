"use client";

import { useMemo, useState } from "react";
import { fmt } from "@/components/charts/TraceChart";
import EvidencePanel from "@/components/evidence/EvidencePanel";
import SeverityTag from "@/components/attention/SeverityTag";
import { SEVERITY_META, type Severity } from "@/lib/types";
import { FindingDetail, PredictionTag, ProfileTable, QualityList, ReviewTag, sameSel, useFullResult, type ViewProps } from "./common";
import { Stat } from "@/components/ui";

const CLASSES = ["Normal", "Side I", "Side II"];

export function RailOverview({ results, selected, onSelect, onReview, summaryItem }: ViewProps) {
  const [filter, setFilter] = useState<string>("all");
  const counts = useMemo(() => {
    const c: Record<string, number> = { Normal: 0, "Side I": 0, "Side II": 0 };
    results.forEach((r) => (c[String(r.items[0]?.prediction)] = (c[String(r.items[0]?.prediction)] ?? 0) + 1));
    return c;
  }, [results]);
  const rows = results.filter((r) => filter === "all" || (filter === "review" ? r.review_count > 0 : r.items[0]?.prediction === filter));
  const sel = results.find((r) => r.id === selected?.resultId)
    ?? [...results].sort((a, b) => SEVERITY_META[(a.items[0]?.triage?.severity ?? "info") as Severity].rank - SEVERITY_META[(b.items[0]?.triage?.severity ?? "info") as Severity].rank
                                  || (a.items[0]?.review_reasons?.length ? 1 : 0) - (b.items[0]?.review_reasons?.length ? 1 : 0))[0] ?? null;
  const isDefault = !results.some((r) => r.id === selected?.resultId);
  const nReview = results.filter((r) => r.review_count > 0).length;
  const thr = (results[0]?.items[0]?.decision as Record<string, number> | undefined)?.stage1_threshold;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-3">
        {CLASSES.map((c) => (
          <Stat key={c} label={c === "Normal" ? "Normal" : `${c} corrugation`} value={counts[c] ?? 0} tone={c !== "Normal" && counts[c] ? "act" : "neutral"}
                pressed={filter === c} onClick={() => setFilter(filter === c ? "all" : c)} />
        ))}
        <Stat label="Uncertain" value={nReview} tone={nReview ? "plan" : "neutral"} pressed={filter === "review"} onClick={() => setFilter(filter === "review" ? "all" : "review")} />
      </div>
      {sel ? (
        <section className="card space-y-4 p-4 md:p-5">
          {isDefault && <p className="text-sm muted">Showing the most important recording first. Select any recording in the table.</p>}
          <FindingDetail item={sel.items[0]} title={sel.file.original_name} subsystem="rail" hideTriage={sameSel(summaryItem, { resultId: sel.id, itemId: sel.items[0].id })}
                         onReview={onReview ? () => onReview({ resultId: sel.id, itemId: sel.items[0].id }) : undefined} />
          <EvidencePanel resultId={sel.id} query={{}} height={220} />
          <QualityList issues={sel.issues} />
        </section>
      ) : (
        <p className="text-sm muted">Select a recording to compare Side I and Side II vibration.</p>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">All recordings <span className="text-sm font-normal muted">· {rows.length} shown{filter !== "all" ? ` (${filter === "review" ? "uncertain" : filter})` : ""}</span></h2>
        {filter !== "all" && <button className="btn btn-ghost btn-sm" onClick={() => setFilter("all")}>Show all</button>}
      </div>
      <div className="card max-h-[520px] overflow-auto">
        <table className="data">
          <thead className="sticky top-0"><tr><th>Recording</th><th>Prediction</th><th>Severity</th><th title="Uncalibrated model score, not a probability">Fault score <span className="font-normal">(fault ≥ {fmt(thr, 2)})</span></th><th>Review</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const it = r.items[0];
              const d = it.decision as Record<string, number> | undefined;
              return (
                <tr key={r.id} className={`clickable ${sel?.id === r.id ? "selected" : ""}`} onClick={() => onSelect({ resultId: r.id, itemId: it.id })}>
                  <td className="mono">{r.file.original_name}</td>
                  <td><PredictionTag value={it.prediction} /></td>
                  <td>{it.triage && it.triage.severity !== "info" ? <SeverityTag severity={it.triage.severity} size="sm" /> : <span className="muted">—</span>}</td>
                  <td className="num">{fmt(d?.stage1_fault_score, 3)}</td>
                  <td><ReviewTag item={it} /></td>
                  <td><button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); onSelect({ resultId: r.id, itemId: it.id }); setTimeout(() => document.getElementById("finding-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); }}>Inspect</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-sm muted">The fault score is an uncalibrated model score, not a probability. Track location is not in the data.</p>
    </div>
  );
}

export function RailExplore({ results, selected, onSelect }: ViewProps) {
  const res = results.find((r) => r.id === selected?.resultId) ?? results[0];
  const [car, setCar] = useState(1);
  const [pos, setPos] = useState(1);
  const [kind, setKind] = useState("vibration");
  const [view, setView] = useState<"waveform" | "psd" | "sides">("waveform");
  const { data } = useFullResult(res?.id ?? null);
  if (!res) return null;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2 font-medium">Recording
          <select className="input" value={res.id}
                  onChange={(e) => { const r = results.find((x) => x.id === e.target.value)!; onSelect({ resultId: r.id, itemId: r.items[0].id }); }}>
            {results.map((r) => <option key={r.id} value={r.id}>{r.file.original_name} · {String(r.items[0]?.prediction)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 font-medium">View
          <select className="input" value={view} onChange={(e) => setView(e.target.value as typeof view)}>
            <option value="waveform">Waveform</option>
            <option value="psd">Frequency spectrum</option>
            <option value="sides">Side comparison</option>
          </select>
        </label>
        {view !== "sides" && (
          <>
            <label className="flex items-center gap-2 font-medium">Car
              <select className="input" value={car} onChange={(e) => setCar(+e.target.value)}>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 font-medium">Axle-box position
              <select className="input" value={pos} onChange={(e) => setPos(+e.target.value)}>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((p) => <option key={p} value={p}>{p} ({p % 2 ? "Side I" : "Side II"})</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 font-medium">Channel
              <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="vibration">Vibration</option>
                <option value="shock">Shock</option>
              </select>
            </label>
          </>
        )}
      </div>
      <EvidencePanel
        resultId={res.id}
        query={view === "sides" ? {} : { view, car, pos, kind }}
        height={260}
        zoomRefetch={view === "waveform" ? { keys: ["t0", "t1"], domain: { x0: 0, x1: 0.9999 } } : undefined}
      />
      <details className="card p-4">
        <summary className="cursor-pointer font-semibold">Channel and feature definitions</summary>
        <ul className="ml-5 mt-2 list-disc text-sm">
          <li>Positions 1, 3, 5, 7 run on the Side I rail; 2, 4, 6, 8 on Side II (8 cars × 8 axle boxes × vibration/shock = 128 channels).</li>
          <li>Features: per-channel RMS, peak, kurtosis, crest factor and Welch band energies (20 Hz–5 kHz), aggregated per side.</li>
          <li>The speed pulse is counted for audit only; it does not enter the model (acquisition-speed confound). No km/h is shown because the conversion is unverified.</li>
          <li>Speed pulse transitions in this file: {String((res.items[0].speed_pulse as Record<string, unknown>)?.transitions ?? "—")}</li>
        </ul>
      </details>
      <section><h3 className="mb-2 text-lg font-semibold">Recording profile</h3><ProfileTable profile={data?.payload.profile} /></section>
    </div>
  );
}
