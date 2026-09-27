"use client";

import { useMemo, useState } from "react";
import { FindingDetail, QualityList, itemLabel, useFullResult, type Sel } from "@/components/analysis/common";
import EvidencePanel from "@/components/evidence/EvidencePanel";
import { EmptyState, ErrorNote } from "@/components/ui";
import { doorClock, doorDate } from "@/lib/format";
import type { ResultRow, Subsystem } from "@/lib/types";

/** Door recorder stamps "2023-7-5-0-23-49-544" → "2023-07-05 00:23:49.544" inside free text. */
const prettyStamps = (t: string) => t.replace(/\b\d{4}(?:-\d{1,3}){6}\b/g, (m) => `${doorDate(m)} ${doorClock(m)}`);

type Finding = { sel: Sel; label: string; reason: string | null };

function findingsOf(results: ResultRow[], subsystem: Subsystem, all: boolean): Finding[] {
  const out: Finding[] = [];
  for (const r of results) {
    for (const it of r.items) {
      if (!all && !it.review_reasons?.length) continue;
      const label = subsystem === "door" ? `${itemLabel(it.id)} · ${String(it.operation ?? "direction unresolved")} · ${it.prediction}`
        : subsystem === "acv" ? `${r.file.original_name}: Car ${String(it.leading_car)} leading`
        : `${r.file.original_name} · ${typeof it.prediction === "number" ? it.prediction.toPrecision(4) : it.prediction}`;
      out.push({ sel: { resultId: r.id, itemId: it.id }, label, reason: it.review_reasons?.[0]?.message ?? null });
    }
  }
  return out;
}

function evidenceQuery(subsystem: Subsystem, item: Record<string, unknown>) {
  if (subsystem === "door") return { item: String(item.id) };
  if (subsystem === "acv") {
    const ranked = item.ranked_cars as string[];
    return { car: String(item.leading_car ?? ranked[0]), compare: ranked[1] };
  }
  return {};
}

/** Findings whose evidence is unusual (near a decision line, outside the training range, a data issue). The model's
 *  answer stands; this view shows why it is uncertain and what to look at. Read-only. */
export default function UncertainPanel({ results, subsystem, selected, onSelect }: {
  results: ResultRow[];
  subsystem: Subsystem;
  selected: Sel | null;
  onSelect: (s: Sel) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const findings = useMemo(() => findingsOf(results, subsystem, showAll), [results, subsystem, showAll]);
  const cur = selected && findings.some((f) => f.sel.resultId === selected.resultId && f.sel.itemId === selected.itemId)
    ? selected : findings[0]?.sel ?? null;
  const { data, error } = useFullResult(cur?.resultId ?? null);

  if (!findings.length) {
    return (
      <EmptyState title="No uncertain findings in this analysis.">
        <p>Every result sits clearly on one side of its decision line, with no data problems.</p>
        <button className="btn mt-3" onClick={() => setShowAll(true)}>Browse all findings anyway</button>
      </EmptyState>
    );
  }
  const item = data?.payload.items.find((i) => i.id === cur?.itemId);
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(240px,320px)_1fr]">
      <aside aria-label="Uncertain findings" className="lg:sticky lg:top-20">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">{showAll ? "All findings" : "Uncertain"} <span className="num font-normal muted">({findings.length})</span></h2>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show all
          </label>
        </div>
        <p className="mb-2 text-sm muted">The model&apos;s answer stands, but the evidence is unusual. Look before relying on it alone.</p>
        <ol className="max-h-[70vh] space-y-1 overflow-auto">
          {findings.map((f) => {
            const active = cur?.resultId === f.sel.resultId && cur?.itemId === f.sel.itemId;
            return (
              <li key={f.sel.resultId + f.sel.itemId}>
                <button onClick={() => onSelect(f.sel)} aria-current={active ? "true" : undefined}
                        className={`w-full rounded-lg border p-2.5 text-left text-sm transition-colors ${active ? "border-accent bg-accent-weak" : "border-line bg-surface hover:border-ink-3"}`}>
                  <span className="block font-semibold">{f.label}</span>
                  <span className="mt-0.5 line-clamp-3 muted">{f.reason ?? "Not flagged as uncertain"}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </aside>
      <section className="space-y-5">
        {error && <ErrorNote>{error}</ErrorNote>}
        {item && cur && (
          <>
            <div className="card p-4 md:p-5">
              <FindingDetail item={item} subsystem={subsystem} title={findings.find((f) => f.sel.itemId === cur.itemId && f.sel.resultId === cur.resultId)?.label ?? item.id} />
              <p className="mt-3 text-sm muted">
                Recorded {prettyStamps(String(data?.payload.profile?.coverage ?? ""))} · {String(data?.payload.recording_context?.freshness ?? "historical upload")}
              </p>
            </div>
            <div className="card p-4 md:p-5">
              <h3 className="mb-3 text-lg font-semibold">Evidence</h3>
              <EvidencePanel resultId={cur.resultId} query={evidenceQuery(subsystem, item)} height={220} />
              <div className="mt-3"><QualityList issues={data?.payload.issues ?? []} /></div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
