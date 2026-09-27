"use client";

import { useEffect, useState } from "react";
import BarChart from "@/components/charts/BarChart";
import TraceChart from "@/components/charts/TraceChart";
import { apiGet, errorText } from "@/lib/api";
import type { Chart } from "@/lib/types";

type Query = Record<string, string | number | undefined | null>;

export function useEvidence(resultId: string | null, query: Query) {
  const [charts, setCharts] = useState<Chart[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify([resultId, query]);
  useEffect(() => {
    if (!resultId) return;
    let live = true;
    setLoading(true);
    setError(null);
    apiGet<{ charts: Chart[] }>(`/api/v1/results/${resultId}/evidence`, query)
      .then((r) => live && setCharts(r.charts))
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { charts, error, loading };
}

export function ChartView({ chart, height, onRangeChange, domain }: {
  chart: Chart;
  height?: number;
  onRangeChange?: (a: number, b: number) => void;
  domain?: { x0: number; x1: number };
}) {
  if (chart.kind === "bar" || chart.kind === "grouped_bar") return <BarChart chart={chart} height={height} />;
  return <TraceChart chart={chart} height={height} onRangeChange={onRangeChange} domain={domain} />;
}

export default function EvidencePanel({ resultId, query, height = 240, zoomRefetch }: {
  resultId: string;
  query: Query;
  height?: number;
  // when set, zooming requests finer data for the visible window using these query keys
  zoomRefetch?: { keys: [string, string]; toParam?: (v: number) => number; domain: { x0: number; x1: number } };
}) {
  const [win, setWin] = useState<Query>({});
  useEffect(() => setWin({}), [JSON.stringify(query)]); // eslint-disable-line react-hooks/exhaustive-deps
  const { charts, error, loading } = useEvidence(resultId, { ...query, ...win });
  if (error) return <p role="alert" className="callout callout-error text-sm">Evidence could not be loaded: {error}</p>;
  if (!charts) return <p className="text-sm muted">{loading ? "Loading evidence…" : ""}</p>;
  return (
    <div className="space-y-6">
      {loading && <p className="text-sm muted" role="status">Updating…</p>}
      {charts.map((c, i) => (
        <ChartView
          key={i + c.title}
          chart={c}
          height={height}
          domain={zoomRefetch?.domain}
          onRangeChange={
            zoomRefetch
              ? (a, b) => {
                  const f = zoomRefetch.toParam ?? ((v: number) => v);
                  const full = a <= zoomRefetch.domain.x0 && b >= zoomRefetch.domain.x1;
                  setWin(full ? {} : { [zoomRefetch.keys[0]]: f(a), [zoomRefetch.keys[1]]: f(b) });
                }
              : undefined
          }
        />
      ))}
    </div>
  );
}
