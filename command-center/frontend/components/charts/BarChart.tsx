"use client";

import { useContainerWidth } from "@/lib/hooks";
import type { Chart } from "@/lib/types";
import { fmt, niceTicks } from "./TraceChart";

const COLORS = ["#1f5fbf", "#374151", "#6b7280"];

export default function BarChart({ chart, height = 220, selected, onSelect }: {
  chart: Chart;
  height?: number;
  selected?: string | null;
  onSelect?: (x: string) => void;
}) {
  const [wrap, W] = useContainerWidth<HTMLDivElement>(900);
  const H = height;
  const M = { l: W < 520 ? 44 : 64, r: 12, t: 14, b: 40 };
  const rawX = chart.series[0]?.x ?? [];
  const cats = rawX.map((x) => (typeof x === "number" ? fmt(x, 3) : String(x)));
  const labelEvery = Math.max(1, Math.ceil(cats.length / Math.max(4, Math.floor(W / 56))));
  const vals = chart.series.flatMap((s) => (s.y ?? []).filter((v): v is number => v !== null && isFinite(v)));
  let y0 = Math.min(0, ...vals);
  let y1 = Math.max(0, ...vals);
  if (y0 === y1) y1 = y0 + 1;
  const pad = (y1 - y0) * 0.08;
  y0 -= y0 < 0 ? pad : 0;
  y1 += pad;
  const bandW = (W - M.l - M.r) / Math.max(1, cats.length);
  const nS = chart.series.length;
  const barW = Math.min(46, (bandW * 0.7) / nS);
  const sy = (y: number) => M.t + (1 - (y - y0) / (y1 - y0)) * (H - M.t - M.b);
  const ticks = niceTicks(y0, y1, 4).filter((v) => v >= y0 && v <= y1);
  return (
    <figure className="w-full">
      <figcaption className="mb-2">
        <span className="font-semibold">{chart.title}</span>{" "}
        <span className="ml-1 text-sm muted">{chart.signal} · {chart.unit}</span>
      </figcaption>
      <div ref={wrap} className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-line bg-surface" role="img"
           aria-label={`${chart.title}. ${chart.caption}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} stroke={v === 0 ? "#9ca3af" : "#eef0f3"} />
            <text x={M.l - 6} y={sy(v) + 4} fontSize="12" textAnchor="end" fill="#4b5563">{fmt(v, 3)}</text>
          </g>
        ))}
        {cats.map((c, i) => {
          const cx = M.l + bandW * (i + 0.5);
          const isSel = selected === c;
          return (
            <g key={c} onClick={() => onSelect?.(c)} style={{ cursor: onSelect ? "pointer" : undefined }}>
              {isSel && <rect x={cx - bandW / 2 + 2} y={M.t} width={bandW - 4} height={H - M.t - M.b} fill="#eef4ff" />}
              {chart.series.map((s, k) => {
                const v = s.y?.[i];
                const x = cx - (barW * nS) / 2 + k * barW;
                if (v === null || v === undefined) {
                  return <text key={k} x={x + barW / 2} y={sy(0) - 4} fontSize="11" textAnchor="middle" fill="#6b7280">n/a</text>;
                }
                const top = Math.min(sy(v), sy(0));
                return <rect key={k} x={x} y={top} width={barW - 2} height={Math.max(1, Math.abs(sy(v) - sy(0)))}
                             fill={COLORS[k % COLORS.length]} opacity={isSel || !selected ? 1 : 0.55}><title>{s.name}: {c}, {fmt(v)} {chart.unit}</title></rect>;
              })}
              {(i % labelEvery === 0 || isSel) && (
                <text x={cx} y={H - M.b + 16} fontSize="12" textAnchor="middle" fill="#1b1f24" fontWeight={isSel ? 700 : 400}>{c}</text>
              )}
            </g>
          );
        })}
        <text x={(M.l + W - M.r) / 2} y={H - 4} fontSize="12" textAnchor="middle" fill="#4b5563">{chart.x_label}</text>
      </svg>
      </div>
      {nS > 1 && (
        <div className="mt-1 flex gap-4 text-sm">
          {chart.series.map((s, k) => (
            <span key={s.name} className="flex items-center gap-1">
              <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm" style={{ background: COLORS[k % COLORS.length] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <p className="mt-1 text-sm muted">{chart.caption}</p>
      <details className="mt-1 text-sm">
        <summary className="cursor-pointer muted">Values as text</summary>
        <table className="data mt-1">
          <thead><tr><th>{chart.x_label}</th>{chart.series.map((s) => <th key={s.name}>{s.name}</th>)}</tr></thead>
          <tbody>
            {cats.map((c, i) => (
              <tr key={c}><td>{c}</td>{chart.series.map((s) => <td key={s.name} className="mono">{fmt(s.y?.[i] ?? null)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
