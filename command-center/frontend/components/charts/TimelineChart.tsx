"use client";

import { useContainerWidth } from "@/lib/hooks";
import type { Chart } from "@/lib/types";
import { doorClock, doorDate, minSec } from "@/lib/format";
import { niceTicks } from "./TraceChart";

export default function TimelineChart({ chart, selected, onSelect }: {
  chart: Chart;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [wrap, W] = useContainerWidth<HTMLDivElement>(900);
  const H = 96;
  const M = { l: 12, r: 12, t: 18, b: 30 };
  const bands = chart.bands;
  const x0 = bands.length ? bands[0].x0 : 0;
  const x1 = bands.length ? bands[bands.length - 1].x1 : 1;
  const sx = (x: number) => M.l + ((x - x0) / Math.max(1e-9, x1 - x0)) * (W - M.l - M.r);
  const native = chart.x_label.match(/since (\S+)/)?.[1];
  const since = native ? `${doorDate(native)} ${doorClock(native).replace(/\.000$/, "")}` : null;
  const ticks = niceTicks(x0 / 60, x1 / 60, W < 520 ? 4 : 8).map((m) => m * 60).filter((v) => v >= x0 && v <= x1);
  return (
    <figure className="w-full">
      <figcaption className="mb-2 font-semibold">{chart.title}</figcaption>
      <div ref={wrap} className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-line bg-surface" role="group"
           aria-label={`${chart.title}: ${bands.length} cycles. Use the table below to select with a keyboard.`}>
        <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="#9ca3af" />
        {ticks.map((v) => (
          <text key={v} x={sx(v)} y={H - M.b + 16} fontSize="12" textAnchor="middle" fill="#4b5563">{minSec(v)}</text>
        ))}
        {bands.map((b) => {
          const w = Math.max(3, sx(b.x1) - sx(b.x0));
          const fault = b.tone === "fault";
          const isSel = selected === b.id;
          return (
            <g key={b.id} onClick={() => b.id && onSelect(b.id)} style={{ cursor: "pointer" }}>
              <title>{`${b.id}: ${b.label}${b.review ? " — review suggested" : ""}`}</title>
              <rect x={sx(b.x0)} y={M.t} width={w} height={H - M.t - M.b} rx={2}
                    fill={fault ? "#b42318" : "#9ca3af"} opacity={isSel ? 1 : 0.75}
                    stroke={isSel ? "#111827" : b.review ? "#d97706" : "none"} strokeWidth={isSel ? 2.5 : b.review ? 2 : 0} />
              {b.review && <text x={sx(b.x0) + w / 2} y={M.t - 4} fontSize="11" textAnchor="middle" fill="#9a6700">!</text>}
            </g>
          );
        })}
      </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-3 w-2 rounded-sm bg-[#9ca3af]" />Normal</span>
        <span className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-3 w-2 rounded-sm bg-act" />Abnormal resistance</span>
        <span className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-3 w-2 rounded-sm border-2 border-[#d97706]" />Uncertain</span>
        <span className="muted">Time axis in minutes:seconds{since ? ` from ${since}` : ""}. Click a cycle to see its signals.</span>
      </div>
    </figure>
  );
}
