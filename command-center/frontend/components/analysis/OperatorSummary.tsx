"use client";

import Link from "next/link";
import Glossed from "@/components/Glossed";
import SeverityTag from "@/components/attention/SeverityTag";
import { SEVERITY_META, type ResultRow, type Severity, type Subsystem } from "@/lib/types";
import type { Sel } from "./common";

type Best = { row: ResultRow; itemIndex: number; rank: number; review: number };

export function topFinding(results: ResultRow[]): { row: ResultRow; itemIndex: number } | null {
  let best: Best | undefined;
  for (const r of results) {
    r.items.forEach((it, i) => {
      const sev = (it.triage?.severity ?? "info") as Severity;
      const rank = SEVERITY_META[sev].rank;
      const review = it.review_reasons?.length ? 1 : 0; // among equal severity prefer findings without review flags (clearer)
      if (!best || rank < best.rank || (rank === best.rank && review < best.review)) best = { row: r, itemIndex: i, rank, review };
    });
  }
  return best ? { row: best.row, itemIndex: best.itemIndex } : null;
}

/** The first thing an operator reads: in plain words, what is wrong, where, how sure we are, and what to do now. */
export default function OperatorSummary({ subsystem, results, onSelect, onReview }: {
  subsystem: Subsystem;
  results: ResultRow[];
  onSelect: (s: Sel) => void;
  onReview?: (s: Sel) => void;
}) {
  const top = topFinding(results);
  if (!top) return null;
  const item = top.row.items[top.itemIndex];
  const t = item.triage;
  if (!t) return null;
  const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0, info: 0 };
  results.forEach((r) => r.items.forEach((it) => { counts[(it.triage?.severity ?? "info") as Severity] += 1; }));
  const total = results.reduce((a, r) => a + r.items.length, 0);
  const summaries = results.map((r) => r.operator_summary?.text).filter(Boolean);
  const oneLine = results.length === 1 ? summaries[0] : `${counts.high} ${counts.high === 1 ? "finding needs" : "findings need"} action, ${counts.medium} to plan, ${counts.low} to watch, across ${total} ${subsystem === "door" ? "door movements" : subsystem === "rail" ? "recordings" : subsystem === "shm" ? "segments" : "cases"}.`;
  const sel: Sel = { resultId: top.row.id, itemId: item.id };
  return (
    <section className={`card opcard opcard-${t.severity} p-4 md:p-5`} aria-labelledby="op-h">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id="op-h" className="text-sm font-semibold uppercase tracking-wide muted">Summary</h2>
          <p className="mt-0.5 text-[1.0625rem] font-medium">{oneLine}</p>
        </div>
        <ul className="flex flex-wrap gap-1.5" aria-label="Findings by severity">
          {(["high", "medium", "low", "info"] as Severity[]).filter((s) => counts[s] > 0).map((s) => (
            <li key={s} className={`tag ${SEVERITY_META[s].cls}`}><span className="num">{counts[s]}</span> {SEVERITY_META[s].label.toLowerCase()}</li>
          ))}
        </ul>
      </div>
      <div className="panel mt-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityTag severity={t.severity} />
          <span className="text-sm muted">{results.length > 1 ? "Most important finding" : "Finding"}</span>
        </div>
        <p className="mt-2 text-lg font-semibold leading-snug"><Glossed text={t.what} subsystem={subsystem} /></p>
        <dl className="kv mt-3">
          <dt>Where</dt><dd>{results.length > 1 && <span className="mono">{top.row.file.original_name} · </span>}<Glossed text={t.where} subsystem={subsystem} /></dd>
          <dt>How sure</dt><dd><Glossed text={t.how_sure} subsystem={subsystem} /></dd>
          <dt>What to check</dt><dd className="font-semibold">{t.action}</dd>
          <dt>Then</dt><dd>{t.next_check}</dd>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn btn-primary btn-sm" onClick={() => onSelect(sel)}>See the evidence</button>
          {onReview && item.review_reasons?.length > 0 && <button className="btn btn-sm" onClick={() => onReview(sel)}>Why it is uncertain</button>}
          <Link className="btn btn-ghost btn-sm" href="/attention">All faults to check</Link>
        </div>
      </div>
      <p className="mt-3 text-xs muted">
        Severity comes from the {t.policy_illustrative ? "illustrative default" : "locally edited"} policy ({t.policy_version}). It is a reading aid, not a
        prediction. This is a historical recording, not a live condition, and it is not linked to an asset unless someone labelled it.
      </p>
    </section>
  );
}
