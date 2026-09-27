"use client";

import { useEffect, useState } from "react";
import { apiGet, errorText } from "@/lib/api";
import { SUBSYSTEM_NAMES, type Subsystem } from "@/lib/types";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";

type Forecast = {
  target: string; inputs_at_origin: string; protocol: string; baseline: string; promotion_rule: string; promoted: boolean;
  horizons: Record<string, { mae_ridge_mean_K: number; mae_persistence_mean_K: number; mean_improvement: number; cases_improved: number; n_cases: number }>;
};
type Splits = { door: string; acv: string; rail: string; shm: string; duplicates: Record<string, number>; created: string };

type Summary = {
  tasks: Record<Subsystem, { version: string; method: string; metric: string; value: number; scope: string; full_set?: number;
    limitations: string[]; comparison?: { name: string; score: number; selected?: boolean }[] }>;
  overall_local: number;
  average_attempted: number;
  updated: string;
  note: string;
};

function Markdown({ text }: { text: string }) {
  // Minimal renderer for the generated model cards: headings, lists, tables, bold, code.
  const lines = text.split("\n");
  const out: JSX.Element[] = [];
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
      p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : <span key={i}>{p}</span>);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith("# ")) out.push(<h1 key={i}>{inline(l.slice(2))}</h1>);
    else if (l.startsWith("## ")) out.push(<h2 key={i}>{inline(l.slice(3))}</h2>);
    else if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[-| ]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
        i++;
      }
      i--;
      out.push(
        <div key={i} className="overflow-x-auto"><table><thead><tr>{rows[0].map((c, k) => <th key={k}>{inline(c)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody></table></div>);
    } else if (l.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2));
      i--;
      out.push(<ul key={i}>{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</ul>);
    } else if (l.trim()) out.push(<p key={i}>{inline(l)}</p>);
  }
  return <div className="prose-md">{out}</div>;
}

export default function Method() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [splits, setSplits] = useState<Splits | null>(null);
  const [cards, setCards] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    apiGet<{ summary: Summary; forecast: Forecast | null; splits: Splits | null }>("/api/v1/methods")
      .then((r) => { setSummary(r.summary); setForecast(r.forecast); setSplits(r.splits); })
      .catch((e) => setError(errorText(e)));
    (["door", "acv", "rail", "shm"] as Subsystem[]).forEach((s) =>
      apiGet<{ model_card: string | null }>(`/api/v1/methods/${s}`).then((r) => setCards((c) => ({ ...c, [s]: r.model_card }))).catch(() => undefined));
  }, []);
  // A link such as /method#rail opens that model card.
  useEffect(() => {
    const openHash = () => {
      const el = document.getElementById(window.location.hash.slice(1));
      if (el instanceof HTMLDetailsElement) { el.open = true; el.scrollIntoView({ block: "start" }); }
    };
    openHash();
    window.addEventListener("hashchange", openHash);
    return () => window.removeEventListener("hashchange", openHash);
  }, [summary]);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Method and validation"
        description="Each subsystem has its own frozen pipeline; uploading a file never trains or re-tunes a model. The figures are local validation results on the supplied training data. They are not organizer scores and do not guarantee held-out performance."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!summary && !error && <Loading />}
      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {(["door", "acv", "rail", "shm"] as Subsystem[]).map((x) => (
            <a key={x} href={`#${x}`} className="card block px-4 py-3 transition-colors hover:border-ink-3">
              <div className="text-sm muted">{SUBSYSTEM_NAMES[x]}</div>
              <div className="num text-2xl font-bold">{summary.tasks[x] ? summary.tasks[x].value.toFixed(3) : "—"}</div>
              <div className="truncate text-xs muted" title={summary.tasks[x]?.metric}>{summary.tasks[x]?.metric ?? "Not trained"}</div>
            </a>
          ))}
          <div className="card col-span-2 border-accent/40 bg-accent-weak px-4 py-3 md:col-span-1">
            <div className="text-sm muted">Local Overall</div>
            <div className="num text-2xl font-bold text-accent">{summary.overall_local.toFixed(3)}</div>
            <div className="text-xs muted">mean of the four tasks</div>
          </div>
        </div>
      )}
      {summary && (
        <section className="card overflow-x-auto">
          <table className="data">
            <thead><tr><th>Subsystem</th><th>Method</th><th>Official metric</th><th>Local validation</th><th>Scope</th></tr></thead>
            <tbody>
              {(["door", "acv", "rail", "shm"] as Subsystem[]).map((s) => {
                const t = summary.tasks[s];
                if (!t) return <tr key={s}><td>{SUBSYSTEM_NAMES[s]}</td><td colSpan={4}>Not trained</td></tr>;
                return (
                  <tr key={s}>
                    <td className="font-semibold"><a href={`#${s}`} className="link">{SUBSYSTEM_NAMES[s]}</a></td>
                    <td>{t.method}<div className="mono text-xs muted">{t.version}</div></td>
                    <td>{t.metric}</td>
                    <td className="num whitespace-nowrap">{t.value.toFixed(3)}{t.full_set !== undefined ? ` (full set ${t.full_set.toFixed(3)})` : ""}</td>
                    <td className="text-sm">{t.scope}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="border-t border-line px-3 py-3 text-sm">
            <p className="num">
              Local Overall = (Door + ACV + Rail + SHM) / 4 = <strong>{summary.overall_local.toFixed(3)}</strong> · Average of attempted
              tasks = <strong>{summary.average_attempted.toFixed(3)}</strong>
            </p>
            <p className="muted">{summary.note} Updated {summary.updated}.</p>
          </div>
        </section>
      )}
      {summary && (
        <section className="card space-y-3 p-4 md:p-5" aria-labelledby="bench-h">
          <h2 id="bench-h" className="text-lg font-semibold">Benchmarking and model selection</h2>
          <p className="text-sm muted">Every subsystem was compared from a simple baseline upward under the same validation folds. The selected model is marked.</p>
          <div className="grid gap-4 md:grid-cols-2">
            {(["door", "acv", "rail", "shm"] as Subsystem[]).map((s) => {
              const t = summary.tasks[s];
              const rows = t?.comparison ?? [];
              const max = Math.max(1e-9, ...rows.map((r) => r.score));
              return (
                <div key={s}>
                  <p className="text-sm font-semibold">{SUBSYSTEM_NAMES[s]} · {t?.metric}</p>
                  <ul className="mt-1 space-y-1">
                    {rows.map((r) => {
                      const chosen = !!r.selected;
                      return (
                        <li key={r.name} className="text-sm">
                          <div className="flex justify-between gap-2"><span className={chosen ? "font-semibold" : ""}>{r.name}{chosen && <span className="tag tag-ok ml-2">Selected</span>}</span><span className="num">{r.score.toFixed(3)}</span></div>
                          <div className="mt-0.5 h-2 rounded bg-line" aria-hidden>
                            <div className={`h-2 rounded ${chosen ? "bg-accent" : "bg-line-strong"}`} style={{ width: `${Math.max(2, (100 * r.score) / max)}%` }} />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>
      )}
      {splits && (
        <section className="card p-4 text-sm md:p-5" aria-labelledby="split-h">
          <h2 id="split-h" className="text-lg font-semibold">Validation splits (no leakage)</h2>
          <ul className="ml-5 mt-1 list-disc space-y-1">
            <li><strong>Door:</strong> {splits.door}; the full segment-and-classify pipeline runs on each held-out block.</li>
            <li><strong>ACV:</strong> {splits.acv}; the ranking rules have no fitted weights.</li>
            <li><strong>Rail:</strong> {splits.rail}; {splits.duplicates?.rail ?? 0} byte-identical training files were found and always kept in the same fold.</li>
            <li><strong>SHM:</strong> {splits.shm}.</li>
            <li>Every partition is saved with file SHA-256 hashes in <span className="mono">reports/validation/split_manifest.json</span>. Official test files were only run through the frozen models.</li>
          </ul>
        </section>
      )}
      {forecast && (
        <section className="card space-y-2 p-4 text-sm md:p-5" aria-labelledby="fc-h">
          <h2 id="fc-h" className="text-lg font-semibold">Forecasting: evaluated, not shipped</h2>
          <p>
            We tested whether ACV cabin temperature can be forecast from information available at the time
            ({forecast.inputs_at_origin}). Protocol: {forecast.protocol}. Baseline: {forecast.baseline}.
          </p>
          <div className="overflow-x-auto">
            <table className="data max-w-2xl rounded-lg border border-line">
              <thead><tr><th>Horizon</th><th>Model MAE</th><th>Persistence MAE</th><th>Change</th><th>Held-out cases improved</th></tr></thead>
              <tbody>
                {Object.entries(forecast.horizons).map(([h, v]) => (
                  <tr key={h}>
                    <td>{h.replace("min", " min")}</td>
                    <td className="num">{v.mae_ridge_mean_K.toFixed(3)} K</td>
                    <td className="num">{v.mae_persistence_mean_K.toFixed(3)} K</td>
                    <td className="num">{v.mean_improvement >= 0 ? "−" : "+"}{Math.abs(v.mean_improvement * 100).toFixed(1)}% error</td>
                    <td className="num">{v.cases_improved} / {v.n_cases}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Decision: {forecast.promoted ? "promoted" : "not promoted"}.</strong> Rule fixed in advance: {forecast.promotion_rule}.
            The forecast does not beat simply assuming no change, so no forecast is shown and none is claimed. Remaining-useful-life
            and failure dates cannot be supported by these datasets (no degradation histories or failure records).
          </p>
        </section>
      )}
      <section className="card p-4 text-sm md:p-5">
        <h2 className="text-lg font-semibold">What this prototype does not claim</h2>
        <ul className="ml-5 mt-1 list-disc">
          <li>No fleet health score, failure probability, remaining useful life or failure date — the four task outputs have different meanings and no calibration against outcomes.</li>
          <li>Maintenance history is not connected, so MTBF and MTTR are not estimable.</li>
          <li>Forecasting was evaluated above and not shipped; details in <span className="mono">reports/forecasting_feasibility.md</span>.</li>
          <li>Results describe historical recordings; they do not certify fitness for service.</li>
        </ul>
      </section>
      <section className="space-y-2" aria-labelledby="cards-h">
        <h2 id="cards-h" className="text-lg font-semibold">Model cards</h2>
        {(["door", "acv", "rail", "shm"] as Subsystem[]).map((s) => (
          <details key={s} id={s} className="card scroll-mt-20 p-4 md:p-5">
            <summary className="cursor-pointer font-semibold">{SUBSYSTEM_NAMES[s]} <span className="font-normal muted">· {summary?.tasks[s]?.version ?? "model card"}</span></summary>
            <div className="mt-3">{cards[s] ? <Markdown text={cards[s]!} /> : <p className="muted">Model card for {SUBSYSTEM_NAMES[s]} not available.</p>}</div>
          </details>
        ))}
      </section>
    </div>
  );
}
