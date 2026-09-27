"use client";

import { useState } from "react";
import BarChart from "@/components/charts/BarChart";
import { fmt } from "@/components/charts/TraceChart";
import EvidencePanel from "@/components/evidence/EvidencePanel";
import type { Item } from "@/lib/types";
import { FindingDetail, ProfileTable, QualityList, sameSel, useFullResult, type ViewProps } from "./common";

type Car = { car: string; rank: number; score_K: number | null; valid_cooling_hours: number; fraction_warmer_than_peers_1K: number | null; sufficient: boolean };
type Case = Item & { ranked_cars: string[]; leading_car: string | null; margin_K: number | null; cars: Car[] };

function CasePicker({ results, value, onChange }: { results: ViewProps["results"]; value: string; onChange: (id: string) => void }) {
  if (results.length < 2) return null;
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      Case
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {results.map((r) => <option key={r.id} value={r.id}>{r.file.original_name}</option>)}
      </select>
    </label>
  );
}

export function AcvOverview({ results, selected, onReview, summaryItem }: ViewProps) {
  const [rid, setRid] = useState(selected?.resultId ?? results[0]?.id);
  const res = results.find((r) => r.id === rid) ?? results[0];
  const { data } = useFullResult(res?.id ?? null);
  if (!res) return null;
  const it = res.items[0] as Case;
  const competing = it.review_reasons.some((r) => r.code === "competing_candidates");
  const second = it.ranked_cars[1];
  return (
    <div className="space-y-5">
      <CasePicker results={results} value={res.id} onChange={setRid} />
      <section aria-labelledby="rank-h">
        <h2 id="rank-h" className="mb-2 text-lg font-semibold">Car ranking <span className="text-sm font-normal muted">· warmest relative to the other cars first</span></h2>
        <ol className="grid grid-cols-4 gap-2 sm:grid-cols-8">
          {it.ranked_cars.map((c, i) => {
            const car = it.cars.find((x) => x.car === c)!;
            return (
              <li key={c} className={`card px-2 py-2 text-center ${i === 0 ? "border-act ring-1 ring-act/30" : ""}`}>
                <div className="text-xs muted">Rank {i + 1}</div>
                <div className="font-bold">Car {c}</div>
                <div className={`num text-sm ${i === 0 ? "font-semibold text-act" : ""}`}>{car.score_K === null ? "no data" : `${car.score_K >= 0 ? "+" : ""}${fmt(car.score_K, 3)} K`}</div>
              </li>
            );
          })}
        </ol>
      </section>
      <section className="card space-y-4 p-4 md:p-5">
        <FindingDetail item={it} subsystem="acv" title={it.leading_car ? `Car ${it.leading_car} is the leading leak candidate` : "No candidate"}
                       hideTriage={sameSel(summaryItem, { resultId: res.id, itemId: it.id })}
                       onReview={onReview ? () => onReview({ resultId: res.id, itemId: it.id }) : undefined} />
        {it.leading_car && (
          <EvidencePanel resultId={res.id} query={{ car: it.leading_car, compare: competing ? second : undefined }} height={240} />
        )}
      </section>
      {data?.payload.overview_chart && <BarChart chart={data.payload.overview_chart} />}
      <div className="card overflow-x-auto">
        <table className="data">
          <thead><tr><th>Rank</th><th>Car</th><th>Score (K)</th><th>Valid cooling</th><th>Time &gt;1 K warmer than peers</th><th>Evidence</th></tr></thead>
          <tbody>
            {it.cars.map((c) => (
              <tr key={c.car}>
                <td>{c.rank}</td>
                <td className="font-semibold">Car {c.car}</td>
                <td className="num">{c.score_K === null ? "—" : fmt(c.score_K, 3)}</td>
                <td className="num">{fmt(c.valid_cooling_hours, 3)} h</td>
                <td className="num">{c.fraction_warmer_than_peers_1K === null ? "—" : `${Math.round(c.fraction_warmer_than_peers_1K * 100)}%`}</td>
                <td>{c.sufficient ? "Scored" : <span className="tag tag-neutral">Too little data; rank is not evidence</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm muted">The benchmark assumes exactly one faulty car per case, so a first-ranked car always exists. On arbitrary real-world files this ranking is not proof of a leak.</p>
      <QualityList issues={res.issues} />
    </div>
  );
}

export function AcvExplore({ results, selected }: ViewProps) {
  const [rid, setRid] = useState(selected?.resultId ?? results[0]?.id);
  const res = results.find((r) => r.id === rid) ?? results[0];
  const it = res?.items[0] as Case | undefined;
  const [car, setCar] = useState<string | null>(null);
  const [cmp, setCmp] = useState<string>("");
  const { data } = useFullResult(res?.id ?? null);
  if (!res || !it) return null;
  const c = car ?? it.leading_car ?? it.ranked_cars[0];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        <CasePicker results={results} value={res.id} onChange={setRid} />
        <label className="flex items-center gap-2 text-sm font-medium">Car
          <select className="input" value={c} onChange={(e) => setCar(e.target.value)}>
            {[...it.ranked_cars].sort().map((x) => <option key={x} value={x}>Car {x}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm font-medium">Compare with
          <select className="input" value={cmp} onChange={(e) => setCmp(e.target.value)}>
            <option value="">(none)</option>
            {[...it.ranked_cars].sort().filter((x) => x !== c).map((x) => <option key={x} value={x}>Car {x}</option>)}
          </select>
        </label>
      </div>
      <EvidencePanel resultId={res.id} query={{ car: c, compare: cmp || undefined }} height={260} />
      <details className="card p-4">
        <summary className="cursor-pointer font-semibold">Score definition and signal mapping</summary>
        <p className="mt-2 text-sm">{String(res.summary?.score_definition ?? "")}</p>
        <p className="mt-1 text-sm muted">Signals used: <span className="mono">{res.summary?.mapping ? Object.keys(res.summary.mapping as object).join(", ") : "—"}</span></p>
      </details>
      <section><h3 className="mb-2 text-lg font-semibold">Recording profile</h3><ProfileTable profile={data?.payload.profile} /></section>
    </div>
  );
}
