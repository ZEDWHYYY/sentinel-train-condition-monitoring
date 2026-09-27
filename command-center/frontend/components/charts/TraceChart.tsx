"use client";

import { useId, useMemo, useRef, useState } from "react";
import { useContainerWidth } from "@/lib/hooks";
import type { Chart, Series } from "@/lib/types";

const COLORS: Record<string, string> = {
  primary: "#1f5fbf",
  reference: "#6b7280",
  secondary: "#374151",
  band: "#9ca3af",
};

type Props = {
  chart: Chart;
  height?: number;
  onRangeChange?: (x0: number, x1: number) => void; // request finer data for a zoomed window
  highlight?: { x0: number; x1: number } | null;
  domain?: { x0: number; x1: number }; // full x-extent when the data shown is a re-fetched window
  xFormat?: (v: number) => string;
};

export function niceTicks(a: number, b: number, n = 6): number[] {
  if (!isFinite(a) || !isFinite(b) || a === b) return [a];
  const span = b - a;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? step0;
  const out: number[] = [];
  for (let v = Math.ceil(a / step) * step; v <= b + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

export function fmt(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(2);
  return (+v.toPrecision(digits)).toString();
}

function seriesXY(s: Series) {
  const xs = s.x as number[];
  const lo = (s.min ?? s.y ?? []) as (number | null)[];
  const hi = (s.max ?? s.y ?? []) as (number | null)[];
  return { xs, lo, hi };
}

export default function TraceChart({ chart, height = 260, onRangeChange, highlight, domain, xFormat }: Props) {
  const [wrap, W] = useContainerWidth<HTMLDivElement>(900);
  const H = height;
  const M = { l: W < 520 ? 46 : 64, r: 12, t: 12, b: 38 };
  const full = useMemo(() => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const s of chart.series) {
      const { xs, lo, hi } = seriesXY(s);
      xs.forEach((x, i) => {
        if (typeof x !== "number") return;
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
        const a = lo[i], b = hi[i];
        if (a !== null && a !== undefined && isFinite(a)) y0 = Math.min(y0, a);
        if (b !== null && b !== undefined && isFinite(b)) y1 = Math.max(y1, b);
      });
    }
    if (!isFinite(x0)) { x0 = 0; x1 = 1; }
    if (!isFinite(y0)) { y0 = 0; y1 = 1; }
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const pad = (y1 - y0) * 0.05;
    if (domain) return { x0: domain.x0, x1: domain.x1, y0: y0 - pad, y1: y1 + pad };
    return { x0, x1: x1 === x0 ? x0 + 1 : x1, y0: y0 - pad, y1: y1 + pad };
  }, [chart, domain]);
  const [view, setView] = useState<{ x0: number; x1: number } | null>(null);
  const [dragMode, setDragMode] = useState(false);
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const clipId = "clip" + useId().replace(/:/g, "");

  const vx0 = view?.x0 ?? full.x0;
  const vx1 = view?.x1 ?? full.x1;
  // y range from visible data
  const yr = useMemo(() => {
    if (!view) return { y0: full.y0, y1: full.y1 };
    let y0 = Infinity, y1 = -Infinity;
    for (const s of chart.series) {
      const { xs, lo, hi } = seriesXY(s);
      xs.forEach((x, i) => {
        if (typeof x !== "number" || x < vx0 || x > vx1) return;
        const a = lo[i], b = hi[i];
        if (a !== null && a !== undefined) y0 = Math.min(y0, a);
        if (b !== null && b !== undefined) y1 = Math.max(y1, b);
      });
    }
    if (!isFinite(y0)) return { y0: full.y0, y1: full.y1 };
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const pad = (y1 - y0) * 0.06;
    return { y0: y0 - pad, y1: y1 + pad };
  }, [chart, view, vx0, vx1, full]);

  const sx = (x: number) => M.l + ((x - vx0) / (vx1 - vx0)) * (W - M.l - M.r);
  const sy = (y: number) => M.t + (1 - (y - yr.y0) / (yr.y1 - yr.y0)) * (H - M.t - M.b);
  const invx = (px: number) => vx0 + ((px - M.l) / (W - M.l - M.r)) * (vx1 - vx0);

  function setRange(a: number, b: number) {
    const lo = Math.max(full.x0, Math.min(a, b));
    const hi = Math.min(full.x1, Math.max(a, b));
    if (hi - lo <= (full.x1 - full.x0) * 1e-4) return;
    const isFull = lo <= full.x0 && hi >= full.x1;
    setView(isFull ? null : { x0: lo, x1: hi });
    onRangeChange?.(lo, hi);
  }
  const zoom = (f: number) => {
    const c = (vx0 + vx1) / 2;
    const h = ((vx1 - vx0) / 2) * f;
    setRange(c - h, c + h);
  };
  const pan = (f: number) => {
    const w = vx1 - vx0;
    let a = vx0 + w * f;
    a = Math.max(full.x0, Math.min(a, full.x1 - w));
    setRange(a, a + w);
  };

  const paths = chart.series.map((s, k) => {
    const { xs, lo, hi } = seriesXY(s);
    const col = COLORS[s.role] ?? COLORS.primary;
    const envelope = s.role === "band";
    const minmax = !envelope && !!s.aggregated && !!s.min && !!s.max;
    const segs: { x: number; lo: number; hi: number }[][] = [];
    let cur: { x: number; lo: number; hi: number }[] = [];
    xs.forEach((x, i) => {
      const a = lo[i], b = hi[i];
      if (typeof x !== "number" || a === null || b === null || a === undefined || b === undefined) {
        if (cur.length) segs.push(cur);
        cur = [];
        return;
      }
      if (x < vx0 - (vx1 - vx0) * 0.02 || x > vx1 + (vx1 - vx0) * 0.02) return;
      cur.push({ x, lo: a, hi: b });
    });
    if (cur.length) segs.push(cur);
    return (
      <g key={k} aria-hidden>
        {segs.map((seg, j) => {
          if (envelope) {
            const top = seg.map((p) => `${sx(p.x).toFixed(1)},${sy(p.hi).toFixed(1)}`);
            const bot = seg.slice().reverse().map((p) => `${sx(p.x).toFixed(1)},${sy(p.lo).toFixed(1)}`);
            return (
              <polygon
                key={j}
                points={[...top, ...bot].join(" ")}
                fill={col}
                fillOpacity={s.role === "band" ? 0.18 : 0.55}
                stroke={s.role === "band" ? "none" : col}
                strokeWidth={s.role === "band" ? 0 : 0.8}
              />
            );
          }
          if (minmax) {
            // min/max stroke trace: each bucket drawn from its min to its max, so every peak stays visible
            const pts = seg.flatMap((p, k) => {
              const a = `${sx(p.x).toFixed(1)},${sy(k % 2 ? p.hi : p.lo).toFixed(1)}`;
              const b = `${sx(p.x).toFixed(1)},${sy(k % 2 ? p.lo : p.hi).toFixed(1)}`;
              return [a, b];
            });
            return (
              <polyline key={j} points={pts.join(" ")} fill="none" stroke={col}
                        strokeWidth={s.role === "primary" ? 1.1 : 1} strokeOpacity={s.role === "primary" ? 1 : 0.85}
                        strokeDasharray={s.role === "reference" ? "5 3" : undefined} />
            );
          }
          return (
            <polyline
              key={j}
              points={seg.map((p) => `${sx(p.x).toFixed(1)},${sy(p.hi).toFixed(1)}`).join(" ")}
              fill="none"
              stroke={col}
              strokeWidth={s.role === "primary" ? 1.6 : 1.2}
              strokeDasharray={s.role === "reference" ? "5 3" : undefined}
            />
          );
        })}
      </g>
    );
  });

  const hoverInfo = useMemo(() => {
    if (hover === null) return null;
    return chart.series.map((s) => {
      const xs = s.x as number[];
      let best = -1, bd = Infinity;
      xs.forEach((x, i) => {
        const d = Math.abs((x as number) - hover);
        if (d < bd) { bd = d; best = i; }
      });
      if (best < 0) return null;
      const lo = (s.min ?? s.y)?.[best];
      const hi = (s.max ?? s.y)?.[best];
      return { name: s.name, role: s.role, x: xs[best], lo, hi, i0: s.i0?.[best], i1: s.i1?.[best], agg: s.aggregated };
    });
  }, [hover, chart]);

  const xt = niceTicks(vx0, vx1, W < 520 ? 4 : 6);
  const yt = niceTicks(yr.y0, yr.y1, 5);
  const primary = chart.series.find((s) => s.role === "primary");
  const pvals = primary ? ([...(primary.min ?? primary.y ?? []), ...(primary.max ?? [])].filter((v) => v !== null && isFinite(v as number)) as number[]) : [];

  return (
    <figure className="w-full">
      <figcaption className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span>
          <span className="font-semibold">{chart.title.replace(/\bcycle-(\d+)/g, "cycle $1")}</span>{" "}
          <span className="ml-1 text-sm muted">{chart.signal} · {chart.unit}{chart.state === "raw" ? "" : ` · ${chart.state}`}</span>
        </span>
        <span className="flex flex-wrap items-center gap-1" role="toolbar" aria-label={`Zoom controls for ${chart.title}`}>
          <button className="btn btn-sm" onClick={() => zoom(0.5)}>Zoom in</button>
          <button className="btn btn-sm" onClick={() => zoom(2)} disabled={!view}>Zoom out</button>
          <button className="btn btn-sm" onClick={() => pan(-0.5)} disabled={!view} aria-label="Pan left">←</button>
          <button className="btn btn-sm" onClick={() => pan(0.5)} disabled={!view} aria-label="Pan right">→</button>
          <button className="btn btn-sm" onClick={() => { setView(null); onRangeChange?.(full.x0, full.x1); }} disabled={!view}>Reset</button>
          <label className="ml-1 flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={dragMode} onChange={(e) => setDragMode(e.target.checked)} />
            Drag to zoom
          </label>
        </span>
      </figcaption>
      <div ref={wrap} className="w-full">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full select-none rounded-lg border border-line bg-surface"
        role="img"
        aria-label={`${chart.title}. ${chart.caption}`}
        onMouseMove={(e) => {
          const r = svgRef.current!.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          if (px < M.l || px > W - M.r) return setHover(null);
          const x = invx(px);
          setHover(x);
          if (drag) setDrag({ ...drag, b: x });
        }}
        onMouseLeave={() => { setHover(null); setDrag(null); }}
        onMouseDown={(e) => {
          if (!dragMode) return;
          const r = svgRef.current!.getBoundingClientRect();
          const x = invx(((e.clientX - r.left) / r.width) * W);
          setDrag({ a: x, b: x });
        }}
        onMouseUp={() => {
          if (drag && Math.abs(drag.b - drag.a) > 0) setRange(drag.a, drag.b);
          setDrag(null);
        }}
      >
        {chart.bands.map((b, i) => (
          <rect key={i} x={sx(Math.max(b.x0, vx0))} y={M.t} width={Math.max(0, sx(Math.min(b.x1, vx1)) - sx(Math.max(b.x0, vx0)))}
                height={H - M.t - M.b} fill={b.tone === "context" ? "#dbeafe" : "#fde68a"} opacity={0.45} />
        ))}
        {highlight && (
          <rect x={sx(highlight.x0)} y={M.t} width={Math.max(2, sx(highlight.x1) - sx(highlight.x0))} height={H - M.t - M.b}
                fill="#fde68a" opacity={0.5} />
        )}
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} stroke="#eef0f3" />
            <text x={M.l - 6} y={sy(v) + 4} fontSize="12" textAnchor="end" fill="#4b5563">{fmt(v, 3)}</text>
          </g>
        ))}
        {xt.map((v) => (
          <g key={`x${v}`}>
            <line x1={sx(v)} x2={sx(v)} y1={H - M.b} y2={H - M.b + 4} stroke="#9ca3af" />
            <text x={sx(v)} y={H - M.b + 16} fontSize="12" textAnchor="middle" fill="#4b5563">{xFormat ? xFormat(v) : fmt(v, 4)}</text>
          </g>
        ))}
        <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="#9ca3af" />
        <text x={(M.l + W - M.r) / 2} y={H - 4} fontSize="12" textAnchor="middle" fill="#4b5563">{chart.x_label}</text>
        <clipPath id={clipId}><rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} /></clipPath>
        <g clipPath={`url(#${clipId})`}>{paths}</g>
        {hover !== null && <line x1={sx(hover)} x2={sx(hover)} y1={M.t} y2={H - M.b} stroke="#111827" strokeDasharray="3 3" />}
        {drag && (
          <rect x={sx(Math.min(drag.a, drag.b))} y={M.t} width={Math.abs(sx(drag.b) - sx(drag.a))} height={H - M.t - M.b}
                fill="#1f5fbf" opacity={0.12} />
        )}
      </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {chart.series.map((s) => (
          <span key={s.name} className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm"
                  style={{ background: COLORS[s.role], opacity: s.role === "band" ? 0.35 : 1 }} />
            {s.name}
          </span>
        ))}
      </div>
      <div className="num mt-1 min-h-[1.5rem] text-sm" aria-live="polite">
        {hoverInfo
          ? hoverInfo.filter(Boolean).map((h) => (
              <span key={h!.name} className="mr-4">
                {h!.name}: {chart.x_label}={fmt(h!.x as number)} → {h!.lo === h!.hi ? fmt(h!.lo as number) : `${fmt(h!.lo as number)} to ${fmt(h!.hi as number)}`} {chart.unit}
                {h!.agg && h!.i0 !== undefined ? ` (min–max of samples ${h!.i0}–${h!.i1})` : h!.i0 !== undefined ? ` (sample ${h!.i0})` : ""}
              </span>
            ))
          : <span className="muted">Hover to read values. Aggregated points show the min–max of the samples they cover.</span>}
      </div>
      <p className="mt-1 text-sm muted">{chart.caption}</p>
      <details className="mt-1 text-sm">
        <summary className="cursor-pointer muted">Chart details and text summary</summary>
        <ul className="ml-5 list-disc">
          <li>Source: <span className="mono">{chart.source}</span></li>
          {chart.reference && <li>Reference: {chart.reference}</li>}
          {primary && pvals.length > 0 && (
            <li>{primary.name}: range {fmt(Math.min(...pvals))} to {fmt(Math.max(...pvals))} {chart.unit}
              {primary.aggregated ? " (display uses min/max buckets; features use full resolution)" : ""}</li>
          )}
        </ul>
      </details>
    </figure>
  );
}
