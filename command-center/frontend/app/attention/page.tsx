"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import Glossed from "@/components/Glossed";
import SeverityTag from "@/components/attention/SeverityTag";
import { apiGet, errorText } from "@/lib/api";
import { localTime, plural } from "@/lib/format";
import { Chevron, EmptyState, ErrorNote, Loading, PageHeader, Stat } from "@/components/ui";
import { SEVERITY_META, SUBSYSTEM_NAMES, type AttentionCard, type Severity, type Subsystem } from "@/lib/types";

// Faults to check: every fault or possible fault from the newest analysis of each recording, grouped by the check
// it calls for. Read-only: this page identifies faults and what to check; it does not track work.
type Feed = {
  cards: AttentionCard[];
  counts: Record<Severity, number>;
  distinct_inputs: number;
  note: string;
};

type Merged = AttentionCard & { siblings: AttentionCard[] };

/** Findings from one recording that share severity, headline and action (e.g. eight abnormal door cycles) become one row. */
function mergeCards(cards: AttentionCard[]): Merged[] {
  const out: Merged[] = [];
  const idx = new Map<string, number>();
  cards.forEach((c) => {
    const k = [c.result_id, c.severity, c.what, c.action].join("|");
    const i = idx.get(k);
    if (i === undefined) { idx.set(k, out.length); out.push({ ...c, siblings: [] }); } else out[i].siblings.push(c);
  });
  return out;
}

/** 8 cars × 2 sides vibration strip for Rail cards; darker = higher RMS; the predicted side is outlined. */
function HeatStrip({ heat }: { heat: NonNullable<AttentionCard["heat"]> }) {
  const all = [...heat.side_I, ...heat.side_II].filter((v) => isFinite(v));
  const max = Math.max(1e-9, ...all);
  const cell = 18, gap = 2, w = heat.cars.length * (cell + gap) + 52, h = 2 * (cell + gap) + 16;
  return (
    <figure className="mt-2">
      <svg width={w} height={h} role="img" aria-label={`Vibration RMS by car and side; highest ${max.toFixed(2)} ${heat.unit}`} className="block max-w-full">
        {(["side_I", "side_II"] as const).map((side, row) => (
          <g key={side} transform={`translate(0,${row * (cell + gap)})`}>
            <text x={0} y={cell - 5} fontSize="11" fill={heat.predicted_side === (side === "side_I" ? "Side I" : "Side II") ? "#b42318" : "#4b5563"}
                  fontWeight={heat.predicted_side === (side === "side_I" ? "Side I" : "Side II") ? 700 : 400}>{side === "side_I" ? "Side I" : "Side II"}</text>
            {heat[side].map((v, i) => (
              <rect key={i} x={52 + i * (cell + gap)} y={0} width={cell} height={cell} rx={2}
                    fill={`rgba(180,35,24,${0.12 + 0.88 * Math.max(0, Math.min(1, v / max))})`}>
                <title>{`Car ${heat.cars[i]}, ${side === "side_I" ? "Side I" : "Side II"}: ${v.toFixed(2)} ${heat.unit}`}</title>
              </rect>
            ))}
          </g>
        ))}
        {heat.cars.map((car, i) => <text key={car} x={52 + i * (cell + gap) + cell / 2} y={h - 3} fontSize="10" textAnchor="middle" fill="#4b5563">{car}</text>)}
      </svg>
      <figcaption className="text-xs muted">Median axle-box vibration RMS per car and side (darker = higher). Corrugation raises both sides; the side label comes from contrast features.</figcaption>
    </figure>
  );
}

const SHORT: Record<Subsystem, string> = { door: "Door", acv: "ACV", rail: "Rail", shm: "SHM" };

/** One finding as a compact row: headline and where. Expands in place for how sure, the next check and the data. */
function Row({ c, flat }: { c: Merged; flat?: boolean }) {
  const [open, setOpen] = useState(false);
  const evidence = `/runs/${c.run_id}?r=${c.result_id}&i=${c.item_id}`;
  const n = c.siblings.length + 1;
  const whereShort = c.where.split(" · ")[0] + (n > 1 ? ` and ${n - 1} more` : "");
  const panel = `f-${c.result_id}-${c.item_id}`;
  return (
    <li className={flat ? "border-t border-line first:border-t-0" : `card opcard opcard-${c.severity}`}>
      <div className="flex items-start gap-3 p-3 md:px-4">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={panel}
                className="flex min-w-0 flex-1 items-start gap-2.5 rounded-md text-left">
          <span className="mt-0.5 text-ink-3"><Chevron open={open} /></span>
          <span className="block min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              {!flat && <SeverityTag severity={c.severity} size="sm" />}
              <span className={`leading-snug ${flat ? "font-medium" : "font-semibold"}`}>{c.what}</span>
              {n > 1 && <span className="tag tag-plain num">{n} findings</span>}
            </span>
            <span className="mt-0.5 block truncate text-sm muted">
              {SHORT[c.subsystem]} · {whereShort}{!c.file || whereShort.includes(c.file) ? "" : ` · ${c.file}`}
            </span>
            {!flat && !open && (
              <span className="mt-1 block text-sm"><span className="font-semibold">Check:</span> {c.action}</span>
            )}
          </span>
        </button>
        <Link className="btn btn-sm hidden shrink-0 sm:inline-flex" href={evidence}>Evidence</Link>
      </div>
      {open && (
        <div id={panel} className="border-t border-line px-4 pb-4 pt-3 md:pl-11">
          <dl className="kv">
            <dt>Where</dt>
            <dd>
              <Glossed text={c.where} subsystem={c.subsystem} />
              {n > 1 && <span className="muted"> · also {c.siblings.slice(0, 6).map((s) => s.where.split(" · ")[0]).join(", ")}{n - 1 > 6 ? ", …" : ""}</span>}
            </dd>
            <dt>How sure</dt><dd><Glossed text={c.how_sure} subsystem={c.subsystem} /></dd>
            {!flat && <><dt>What to check</dt><dd className="font-semibold">{c.action}</dd></>}
            <dt>Then</dt><dd>{c.next_check}</dd>
            <dt>Data</dt><dd><span className="mono">{c.file}</span> · analysed {localTime(c.analysed)}</dd>
          </dl>
          {c.heat && <HeatStrip heat={c.heat} />}
          <div className="mt-4">
            <Link className="btn btn-primary btn-sm" href={evidence}>See the evidence</Link>
          </div>
        </div>
      )}
    </li>
  );
}

type CheckGroup = { key: string; severity: Severity; action: string; cards: Merged[] };

/** Findings that call for the same check become one numbered item: the check is the headline, the faults found are
 *  listed underneath (each opens for its evidence). */
function groupByCheck(cards: Merged[]): CheckGroup[] {
  const out: CheckGroup[] = [];
  const idx = new Map<string, number>();
  cards.forEach((c) => {
    const k = [c.severity, c.subsystem, c.action].join("|");
    const i = idx.get(k);
    if (i === undefined) { idx.set(k, out.length); out.push({ key: k, severity: c.severity, action: c.action, cards: [c] }); }
    else out[i].cards.push(c);
  });
  return out;
}

function CheckItem({ g, n }: { g: CheckGroup; n: number }) {
  const total = g.cards.reduce((a, c) => a + c.siblings.length + 1, 0);
  const recordings = new Set(g.cards.map((c) => c.result_id)).size;
  const subsystem = g.cards[0].subsystem;
  return (
    <li className={`card opcard opcard-${g.severity}`}>
      <div className="flex items-start gap-3 border-b border-line p-3 md:px-4 md:py-4">
        <span aria-hidden className="num mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">{n}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <SeverityTag severity={g.severity} size="sm" />
            <span className="muted">
              {SUBSYSTEM_NAMES[subsystem]} · {plural(total, "finding")}{recordings > 1 ? ` in ${plural(recordings, "recording")}` : ""}
            </span>
          </div>
          <p className="mt-1.5 font-semibold leading-snug md:text-[1.0625rem]">
            <span className="sr-only">Check {n}: </span>
            {recordings > 1 && <span className="font-normal muted">For each recording below: </span>}
            {g.action}
          </p>
        </div>
      </div>
      <ol aria-label={`Findings for check ${n}`}>
        {g.cards.map((c) => <Row key={c.result_id + c.item_id} c={c} flat />)}
      </ol>
    </li>
  );
}

/** First run: nothing analysed yet. Explain the three steps and point at the one button that starts them. */
function GetStarted() {
  const steps = [
    { t: "Add recordings", d: "Upload Door, ACV, Rail or SHM files, or pick the official test sets already on this computer." },
    { t: "SENTINEL identifies faults", d: "It recognises each file, flags anything it cannot use, and applies the frozen model. Nothing is trained on your data." },
    { t: "See what to check", d: "Faults land here grouped by the check they call for, most urgent first, each with the evidence behind it." },
  ];
  return (
    <section className="card p-6 md:p-8" aria-labelledby="start-h">
      <h2 id="start-h" className="text-xl font-semibold">Start by analysing some data</h2>
      <p className="mt-1 max-w-prose muted">Nothing has been analysed on this computer yet. The official test sets are the quickest way to try it.</p>
      <ol className="mt-6 grid gap-4 md:grid-cols-3">
        {steps.map((x, i) => (
          <li key={x.t} className="panel p-4">
            <span aria-hidden className="num flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">{i + 1}</span>
            <p className="mt-2 font-semibold">{x.t}</p>
            <p className="mt-1 text-sm muted">{x.d}</p>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Link className="btn btn-primary" href="/analyze">Start a new analysis</Link>
        <Link className="btn btn-ghost" href="/learn">New to these subsystems? Read Learn first</Link>
      </div>
    </section>
  );
}

export default function FaultsToCheck() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sev, setSev] = useState<Severity | "all">("all");
  const [sub, setSub] = useState<Subsystem | "all">("all");
  const [showInfo, setShowInfo] = useState(false);
  const [grouped, setGrouped] = useState(true);
  const load = useCallback(() => {
    apiGet<Feed>("/api/v1/attention", { include_info: showInfo ? "true" : "" })
      .then(setFeed).catch((e) => setError(errorText(e)));
  }, [showInfo]);
  useEffect(() => { load(); }, [load]);
  const cards = useMemo(() => mergeCards((feed?.cards ?? []).filter((c) => (sev === "all" || c.severity === sev) && (sub === "all" || c.subsystem === sub))), [feed, sev, sub]);
  const checks = useMemo(() => groupByCheck(cards), [cards]);
  const total = feed ? feed.counts.high + feed.counts.medium + feed.counts.low + (showInfo ? feed.counts.info : 0) : 0;
  const filtered = sev !== "all" || sub !== "all";
  const nFindings = cards.reduce((a, c) => a + c.siblings.length + 1, 0);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Faults to check"
        description="Faults and possible faults found in your recordings, grouped by what to check, most urgent first. These are historical recordings, not live condition."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!feed && !error && <Loading />}
      {feed && feed.distinct_inputs === 0 && <GetStarted />}
      {feed && feed.distinct_inputs > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap">
            <Stat label="All findings" value={total} pressed={sev === "all"} onClick={() => setSev("all")} />
            {(["high", "medium", "low"] as Severity[]).map((s) => (
              <Stat key={s} label={SEVERITY_META[s].label} value={feed.counts[s]} tone={s === "high" ? "act" : s === "medium" ? "plan" : "watch"}
                    pressed={sev === s} onClick={() => setSev(sev === s ? "all" : s)} hint={SEVERITY_META[s].hint} />
            ))}
            <div className="hidden sm:ml-auto sm:flex">
              <Stat label="Recordings analysed" value={feed.distinct_inputs} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-y border-line py-3 text-sm">
            <label className="flex items-center gap-2 font-medium">
              Subsystem
              <select className="input" value={sub} onChange={(e) => setSub(e.target.value as Subsystem | "all")}>
                <option value="all">All subsystems</option>
                {(["door", "acv", "rail", "shm"] as Subsystem[]).map((s) => <option key={s} value={s}>{SUBSYSTEM_NAMES[s]}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} /> Group by what to check</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={showInfo} onChange={(e) => setShowInfo(e.target.checked)} /> Also show normal results</label>
            {filtered && <button className="btn btn-ghost btn-sm ml-auto" onClick={() => { setSev("all"); setSub("all"); }}>Clear filters</button>}
          </div>
          {cards.length === 0 ? (
            <EmptyState title={filtered ? "No findings for this filter." : "No faults found."}>
              {filtered
                ? <button className="btn btn-sm mt-2" onClick={() => { setSev("all"); setSub("all"); }}>Clear filters</button>
                : <>All {plural(feed.distinct_inputs, "analysed recording")} look normal. <Link className="link" href="/analyze">Analyse more data</Link>.</>}
            </EmptyState>
          ) : grouped ? (
            <section aria-labelledby="todo-h" className="space-y-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="todo-h" className="text-lg font-semibold">What to check, most urgent first</h2>
                <p className="text-sm muted">{plural(checks.length, "check")} covering {plural(nFindings, "finding")}. Open a finding for its evidence.</p>
              </div>
              <ol className="space-y-3">{checks.map((g, i) => <CheckItem key={g.key} g={g} n={i + 1} />)}</ol>
            </section>
          ) : (
            <ol className="space-y-2" aria-label="Findings, most urgent first">{cards.map((c) => <Row key={c.result_id + c.item_id} c={c} />)}</ol>
          )}
          <p className="text-xs muted">
            {feed.note} Severity (Act now / Plan a check / Watch) orders the list; it is a reading aid set by an illustrative policy, not part of the prediction.
          </p>
        </>
      )}
    </div>
  );
}
