"use client";

import { useEffect, useRef, useState } from "react";
import TimelineChart from "@/components/charts/TimelineChart";
import { fmt } from "@/components/charts/TraceChart";
import EvidencePanel from "@/components/evidence/EvidencePanel";
import { doorClock, doorDate } from "@/lib/format";
import type { Item } from "@/lib/types";
import { FindingDetail, PredictionTag, ProfileTable, QualityList, ReviewTag, itemLabel, mostImportant, sameSel, useFullResult, type ViewProps } from "./common";
import { Stat } from "@/components/ui";
import SeverityTag from "@/components/attention/SeverityTag";

type Cycle = Item & { start_time: string; end_time: string; operation: string | null; features: Record<string, number> };

function StreamPicker({ results, value, onChange }: { results: ViewProps["results"]; value: string; onChange: (id: string) => void }) {
  if (results.length < 2) return null;
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      Stream
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {results.map((r) => <option key={r.id} value={r.id}>{r.file.original_name}</option>)}
      </select>
    </label>
  );
}

function defaultCycle(items: Cycle[]): Cycle | undefined {
  return mostImportant(items) ?? items[0];
}


export function DoorOverview({ results, selected, onSelect, onReview, summaryItem }: ViewProps) {
  const [rid, setRid] = useState(selected?.resultId ?? results[0]?.id);
  const res = results.find((r) => r.id === rid) ?? results[0];
  const { data } = useFullResult(res?.id ?? null);
  const detailRef = useRef<HTMLElement>(null);
  const clicked = useRef(false);
  const items = (res?.items ?? []) as Cycle[];
  const sel = (selected?.resultId === res?.id ? items.find((i) => i.id === selected?.itemId) : undefined) ?? defaultCycle(items);
  useEffect(() => {
    if (clicked.current) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    clicked.current = false;
  }, [sel?.id]);
  if (!res) return null;
  const pick = (id: string) => {
    clicked.current = true;
    onSelect({ resultId: res.id, itemId: id });
  };
  const notes = (res.summary?.stream_notes as string[]) ?? [];
  const n = items.length;
  const abn = items.filter((i) => i.prediction === "Abnormal resistance").length;
  const rev = items.filter((i) => i.review_reasons.length).length;
  const isDefault = !(selected?.resultId === res.id && items.some((i) => i.id === selected.itemId));
  return (
    <div className="space-y-5">
      <StreamPicker results={results} value={res.id} onChange={setRid} />
      <div className="flex flex-wrap gap-3">
        <Stat label="Cycles found" value={n} />
        <Stat label="Abnormal resistance" value={abn} tone={abn ? "act" : "neutral"} />
        <Stat label="Normal" value={n - abn} />
        <Stat label="Uncertain" value={rev} tone={rev ? "plan" : "neutral"} />
      </div>
      {notes.length > 0 && (
        <div className="callout callout-warn text-sm">
          <strong className="text-plan">Evidence limitation.</strong>{" "}
          {notes.map((t) => t.split(" This door")[0]).join(" ")} This door or its condition may differ from the single
          training door, so labels near the cutoff are uncertain and are marked for review.
        </div>
      )}
      {data?.payload.overview_chart && (
        <TimelineChart chart={data.payload.overview_chart} selected={sel?.id ?? null} onSelect={pick} />
      )}
      {sel && (
        <section ref={detailRef} className="card scroll-mt-20 space-y-4 p-4 md:p-5" aria-live="polite">
          {isDefault && <p className="text-sm muted">Showing the most important cycle first. Select any cycle in the timeline or the table.</p>}
          <FindingDetail item={sel} subsystem="door" hideTriage={sameSel(summaryItem, { resultId: res.id, itemId: sel.id })}
                         title={`${itemLabel(sel.id)} · ${sel.operation ?? "direction unresolved"} · ${doorClock(sel.start_time)}–${doorClock(sel.end_time)}`}
                         onReview={onReview ? () => onReview({ resultId: res.id, itemId: sel.id }) : undefined} />
          <EvidencePanel resultId={res.id} query={{ item: sel.id }} height={220} />
        </section>
      )}
      <section aria-labelledby="cycles-h">
        <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
          <h2 id="cycles-h" className="text-lg font-semibold">All cycles</h2>
          <span className="text-sm muted">Recorded {items[0] ? doorDate(items[0].start_time) : ""}; times are the recorder&apos;s clock.</span>
        </div>
        <div className="card max-h-[28rem] overflow-auto">
          <table className="data">
            <thead className="sticky top-0">
              <tr><th>Cycle</th><th>Start–end</th><th>Movement</th><th>Current integral</th><th>Prediction</th><th>Severity</th><th>Review</th></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className={`clickable ${sel?.id === c.id ? "selected" : ""}`} onClick={() => pick(c.id)}>
                  <td>
                    <button className="num font-semibold text-accent underline-offset-2 hover:underline" aria-label={`Show ${itemLabel(c.id)}`} onClick={(e) => { e.stopPropagation(); pick(c.id); }}>
                      {c.id.replace("cycle-", "")}
                    </button>
                  </td>
                  <td className="num whitespace-nowrap text-sm">{doorClock(c.start_time)}–{doorClock(c.end_time)}</td>
                  <td>{c.operation ?? <span className="text-review">unresolved</span>}</td>
                  <td className="num whitespace-nowrap">{fmt(c.features?.current_integral_mAs)} mA·s</td>
                  <td><PredictionTag value={c.prediction} /></td>
                  <td>{c.triage && c.triage.severity !== "info" ? <SeverityTag severity={c.triage.severity} size="sm" /> : <span className="muted">—</span>}</td>
                  <td><ReviewTag item={c} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <QualityList issues={res.issues} />
    </div>
  );
}

export function DoorExplore({ results, selected, onSelect }: ViewProps) {
  const [rid, setRid] = useState(selected?.resultId ?? results[0]?.id);
  const res = results.find((r) => r.id === rid) ?? results[0];
  const { data } = useFullResult(res?.id ?? null);
  if (!res) return null;
  const items = res.items as Cycle[];
  const itemId = selected?.resultId === res.id ? selected.itemId : defaultCycle(items)?.id;
  const seg = res.summary?.segmentation as { gap_histogram?: { edges_s: (number | string)[]; counts: number[] } } | undefined;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        <StreamPicker results={results} value={res.id} onChange={setRid} />
        <label className="flex items-center gap-2 text-sm font-medium">
          Cycle
          <select className="input" value={itemId}
                  onChange={(e) => onSelect({ resultId: res.id, itemId: e.target.value })}>
            {items.map((c) => (
              <option key={c.id} value={c.id}>
                {itemLabel(c.id)} · {c.operation ?? "direction unresolved"} · {c.prediction}{c.review_reasons.length ? " · uncertain" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {itemId && <EvidencePanel resultId={res.id} query={{ item: itemId }} height={260} />}
      <details className="card p-4">
        <summary className="cursor-pointer font-semibold">How cycles are found and classified</summary>
        <ul className="ml-5 mt-2 list-disc space-y-1 text-sm">
          <li>A new cycle starts wherever consecutive rows are more than 1 s apart. In training, rows inside a cycle are 0.02 s apart and cycles are at least 10.2 s apart; gaps in between would be flagged.</li>
          <li>Current integral = Σ motor current × elapsed time over the cycle (mA·s), computed on every row.</li>
          <li>Direction is inferred from four cues (commands, motion flags, close switches, position trend); disagreement leaves it unresolved and flags review.</li>
          <li>Each direction has its own frozen cutoff because Normal and Abnormal ranges overlap when directions are pooled.</li>
        </ul>
        {seg?.gap_histogram && (
          <table className="data mt-3 max-w-xl text-sm">
            <thead><tr><th>Gap between rows</th><th>Count in this stream</th></tr></thead>
            <tbody>
              {seg.gap_histogram.counts.map((c, i) => (
                <tr key={i}><td>{String(seg.gap_histogram!.edges_s[i])}–{String(seg.gap_histogram!.edges_s[i + 1])} s</td><td className="mono">{c}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
      <section>
        <h3 className="mb-2 text-lg font-semibold">Recording profile</h3>
        <ProfileTable profile={data?.payload.profile} />
      </section>
    </div>
  );
}
