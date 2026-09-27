"use client";

import { useState } from "react";
import BarChart from "@/components/charts/BarChart";
import { fmt } from "@/components/charts/TraceChart";
import EvidencePanel from "@/components/evidence/EvidencePanel";
import SeverityTag from "@/components/attention/SeverityTag";
import { SEVERITY_META, type Chart, type Severity } from "@/lib/types";
import { FindingDetail, ProfileTable, QualityList, ReviewTag, sameSel, useFullResult, type ViewProps } from "./common";

export function ShmOverview({ results, selected, onSelect, onReview, summaryItem }: ViewProps) {
  const sel = results.find((r) => r.id === selected?.resultId)
    ?? [...results].sort((a, b) => SEVERITY_META[(a.items[0]?.triage?.severity ?? "info") as Severity].rank - SEVERITY_META[(b.items[0]?.triage?.severity ?? "info") as Severity].rank)[0] ?? null;
  const isDefault = !results.some((r) => r.id === selected?.resultId);
  const est: Chart = {
    kind: "bar", title: "Estimated cumulative damage by file", signal: "Cumulative fatigue damage", unit: "dimensionless",
    x_label: "File", source: "this analysis", state: "model output", reference: null,
    series: [{ name: "estimate", role: "primary", x: results.map((r) => r.file.original_name.replace(/\.csv$/i, "")),
               y: results.map((r) => (typeof r.items[0]?.prediction === "number" ? (r.items[0].prediction as number) : null)) }],
    markers: [], bands: [],
    caption: "File numbers are arbitrary identifiers, not a time order — this is not a deterioration trend.",
  };
  return (
    <div className="space-y-5">
      <BarChart chart={est} height={220} selected={sel?.file.original_name.replace(/\.csv$/i, "") ?? null}
                onSelect={(x) => { const r = results.find((q) => q.file.original_name.replace(/\.csv$/i, "") === x); if (r) onSelect({ resultId: r.id, itemId: r.items[0].id }); }} />
      {sel ? (
        <section className="card space-y-4 p-4 md:p-5">
          {isDefault && <p className="text-sm muted">Showing the most important file first. Select a bar or a table row to change.</p>}
          <FindingDetail item={sel.items[0]} title={sel.file.original_name} subsystem="shm" hideTriage={sameSel(summaryItem, { resultId: sel.id, itemId: sel.items[0].id })}
                         onReview={onReview ? () => onReview({ resultId: sel.id, itemId: sel.items[0].id }) : undefined} />
          <EvidencePanel resultId={sel.id} query={{}} height={220} />
          <QualityList issues={sel.issues} />
        </section>
      ) : (
        <p className="text-sm muted">Select a file to see its stress trace and counted cycles.</p>
      )}
      <h2 className="text-lg font-semibold">All files</h2>
      <div className="card overflow-x-auto">
        <table className="data">
          <thead><tr><th>File</th><th>Estimated damage</th><th>Severity</th><th>Peak-to-peak stress</th><th>Review</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {results.map((r) => {
              const it = r.items[0];
              const f = it.features as Record<string, number> | undefined;
              return (
                <tr key={r.id} className={`clickable ${sel?.id === r.id ? "selected" : ""}`} onClick={() => onSelect({ resultId: r.id, itemId: it.id })}>
                  <td className="mono">{r.file.original_name}</td>
                  <td className="num">{typeof it.prediction === "number" ? fmt(it.prediction, 4) : "unavailable"}</td>
                  <td>{it.triage && it.triage.severity !== "info" ? <SeverityTag severity={it.triage.severity} size="sm" /> : <span className="muted">—</span>}</td>
                  <td className="num">{fmt(f?.p2p, 4)}</td>
                  <td><ReviewTag item={it} /></td>
                  <td><button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); onSelect({ resultId: r.id, itemId: it.id }); setTimeout(() => document.getElementById("finding-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); }}>Inspect</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-sm muted">Damage is a Miner-type cumulative damage value as defined by the dataset. It is not a remaining-life figure or a failure date.</p>
    </div>
  );
}

export function ShmExplore({ results, selected, onSelect }: ViewProps) {
  const res = results.find((r) => r.id === selected?.resultId) ?? results[0];
  const [view, setView] = useState<"trace" | "cycles">("trace");
  const { data } = useFullResult(res?.id ?? null);
  if (!res) return null;
  const n = (data?.payload.profile?.rows as number) ?? 581120;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2 font-medium">File
          <select className="input" value={res.id}
                  onChange={(e) => { const r = results.find((x) => x.id === e.target.value)!; onSelect({ resultId: r.id, itemId: r.items[0].id }); }}>
            {results.map((r) => <option key={r.id} value={r.id}>{r.file.original_name}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 font-medium">View
          <select className="input" value={view} onChange={(e) => setView(e.target.value as typeof view)}>
            <option value="trace">Stress trace</option>
            <option value="cycles">Counted cycles</option>
          </select>
        </label>
      </div>
      <EvidencePanel resultId={res.id} query={{ view: view === "cycles" ? "cycles" : "trace" }} height={260}
                     zoomRefetch={view === "trace" ? { keys: ["i0", "i1"], toParam: (v) => Math.round(v), domain: { x0: 0, x1: n - 1 } } : undefined} />
      <details className="card p-4">
        <summary className="cursor-pointer font-semibold">Feature definitions</summary>
        <ul className="ml-5 mt-2 list-disc text-sm">
          <li>Reversals are extracted after removing repeated values; excursions smaller than the frozen gate are ignored (hysteresis filter).</li>
          <li>Cycles are counted with three-point (ASTM E1049) rainflow; ranges are peak-to-valley (twice the amplitude).</li>
          <li>Damage estimate = c · Σ nᵢ · rangeᵢ^m with c and m fitted on training files only; material S–N constants were not supplied.</li>
          <li>The sampling rate is not documented, so the axis is the sample index.</li>
        </ul>
      </details>
      <section><h3 className="mb-2 text-lg font-semibold">Recording profile</h3><ProfileTable profile={data?.payload.profile} /></section>
    </div>
  );
}
