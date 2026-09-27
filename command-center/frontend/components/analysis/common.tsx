"use client";

import { useEffect, useState } from "react";
import Glossed from "@/components/Glossed";
import SeverityTag from "@/components/attention/SeverityTag";
import { fmt } from "@/components/charts/TraceChart";
import { apiGet, errorText } from "@/lib/api";
import { SEVERITY_META, type FullResult, type Item, type QualityIssue, type ResultRow, type Severity } from "@/lib/types";

export type Sel = { resultId: string; itemId: string };

export type ViewProps = {
  results: ResultRow[];
  selected: Sel | null;
  onSelect: (s: Sel) => void;
  onReview?: (s: Sel) => void;
  /** The finding the summary card above already describes (its What / How sure / What to check is not repeated). */
  summaryItem?: Sel | null;
};

export const sameSel = (a?: Sel | null, b?: Sel | null) => !!a && !!b && a.resultId === b.resultId && a.itemId === b.itemId;

export function useFullResult(id: string | null) {
  const [data, setData] = useState<FullResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!id) return;
    let live = true;
    apiGet<FullResult>(`/api/v1/results/${id}`)
      .then((r) => live && setData(r))
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [id]);
  return { data, error };
}

const FAULT = new Set(["Abnormal resistance", "Side I", "Side II"]);

/** "cycle-033" → "Cycle 033"; other ids pass through. */
export function itemLabel(id: string): string {
  return id.replace(/^cycle-/, "Cycle ");
}

export function PredictionTag({ value }: { value: Item["prediction"] }) {
  if (value === null || value === undefined) return <span className="tag tag-neutral">Unavailable</span>;
  if (typeof value === "number") return <span className="tag tag-neutral num">{fmt(value)}</span>;
  if (FAULT.has(value)) return <span className="tag tag-fault"><span aria-hidden>▲</span>{value}</span>;
  if (value === "Normal") return <span className="tag tag-ok">{value}</span>;
  return <span className="tag tag-neutral">{value}</span>;
}

/** In tables: an amber "Review" badge, or a dash. `hideNone` renders nothing when there is no trigger. */
export function ReviewTag({ item, hideNone }: { item: Item; hideNone?: boolean }) {
  const n = item.review_reasons?.length ?? 0;
  if (n) return <span className="tag tag-review" title={item.review_reasons.map((r) => r.message).join("\n")}><span aria-hidden>!</span>Uncertain{n > 1 ? ` (${n})` : ""}</span>;
  if (hideNone) return null;
  return <span className="muted" aria-label="Not uncertain">—</span>;
}

/** Pick the finding an operator should see first: highest severity, then clearest (fewest review flags). */
export function mostImportant<T extends Item>(items: T[]): T | undefined {
  let best: { it: T; key: [number, number] } | undefined;
  items.forEach((it) => {
    const key: [number, number] = [SEVERITY_META[(it.triage?.severity ?? "info") as Severity].rank, it.review_reasons?.length ? 1 : 0];
    if (!best || key[0] < best.key[0] || (key[0] === best.key[0] && key[1] < best.key[1])) best = { it, key };
  });
  return best?.it;
}

/** Evidence for one finding. `hideTriage` drops the What / How sure / What to check block when the summary card above
 *  already shows it for the same finding. */
export function FindingDetail({ item, title, onReview, subsystem, hideTriage }: {
  item: Item; title: string; onReview?: () => void; subsystem?: string; hideTriage?: boolean;
}) {
  const t = item.triage;
  return (
    <div id="finding-detail" className="scroll-mt-20 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="mr-1 text-lg font-semibold">{title}</h3>
        {t && <SeverityTag severity={t.severity} />}
        <PredictionTag value={item.prediction} />
        <ReviewTag item={item} hideNone />
      </div>
      {t && !hideTriage && (
        <dl className="kv panel p-3">
          <dt>What</dt><dd><Glossed text={t.what} subsystem={subsystem} /></dd>
          <dt>How sure</dt><dd><Glossed text={t.how_sure} subsystem={subsystem} /></dd>
          <dt>What to check</dt><dd className="font-semibold">{t.action}</dd>
        </dl>
      )}
      {item.observations?.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold muted">Evidence in numbers</h4>
          <ul className="mt-1 ml-5 list-disc space-y-1">
            {item.observations.slice(0, 4).map((o, i) => <li key={i}><Glossed text={o} subsystem={subsystem} /></li>)}
          </ul>
        </div>
      )}
      {item.review_reasons?.length > 0 && (
        <div className="callout callout-warn">
          <p className="font-semibold text-plan">Why this finding is uncertain</p>
          <ul className="mt-1 space-y-2">
            {item.review_reasons.map((r) => (
              <li key={r.code}>
                <Glossed text={r.message} subsystem={subsystem} />
                <div className="text-sm"><strong>Next check:</strong> {r.next_check}</div>
              </li>
            ))}
          </ul>
          {onReview && <button className="btn btn-sm mt-2" onClick={onReview}>See all uncertain findings</button>}
        </div>
      )}
    </div>
  );
}

export function QualityList({ issues }: { issues: QualityIssue[] }) {
  if (!issues?.length) return <p className="text-sm muted">Data quality: no issues found by the checks.</p>;
  return (
    <div>
      <h4 className="text-sm font-semibold muted">Data quality</h4>
      <ul className="mt-1 space-y-1 text-sm">
        {issues.map((i, k) => (
          <li key={k} className="flex flex-wrap items-baseline gap-x-2">
            <span className={`tag ${i.severity === "info" ? "tag-neutral" : "tag-review"}`}>{i.severity}</span>
            <span>{i.description} <span className="muted">— {i.treatment}{i.effect !== "None on prediction." ? ` ${i.effect}` : ""}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ProfileTable({ profile }: { profile: FullResult["payload"]["profile"] | undefined }) {
  if (!profile) return null;
  const ch = (profile.channels as Record<string, unknown>[]) ?? [];
  return (
    <div className="space-y-2 text-sm">
      <p className="num">
        <strong>{profile.rows?.toLocaleString()}</strong> rows · <strong>{profile.columns}</strong> columns · coverage {profile.coverage} ·
        sample rate {profile.sample_rate_hz ? `${fmt(profile.sample_rate_hz)} Hz` : "unknown"} ({profile.sample_rate_source})
      </p>
      <div className="card overflow-x-auto">
        <table className="data">
          <thead><tr><th>Signal</th><th>Kind</th><th>Min</th><th>Median</th><th>Max</th><th>Missing</th></tr></thead>
          <tbody>
            {ch.slice(0, 20).map((c, i) => (
              <tr key={i}>
                <td>{String(c.name)}</td>
                <td>{String(c.kind ?? "")}{c.unit ? ` · ${c.unit}` : ""}</td>
                <td className="mono">{fmt(c.min as number)}</td>
                <td className="mono">{fmt(c.median as number)}</td>
                <td className="mono">{fmt(c.max as number)}</td>
                <td className="mono">{c.missing !== undefined ? String(c.missing) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
