"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import TraceChart from "@/components/charts/TraceChart";
import { apiGet, errorText } from "@/lib/api";
import type { Chart } from "@/lib/types";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";

type Explore = { file: string; rows: number; columns: string[]; numeric_columns: number; charts: Chart[]; missing_requirement: string | null };

export default function ExplorePage() {
  const { fileId } = useParams<{ fileId: string }>();
  const [d, setD] = useState<Explore | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    apiGet<Explore>(`/api/v1/files/${fileId}/explore`).then(setD).catch((e) => setError(errorText(e)));
  }, [fileId]);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <Loading />;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={<Link href="/analyze" className="link">← Back to New analysis</Link>} title={<>Explore <span className="mono text-[0.9em]">{d.file}</span></>} />
      <p className="callout callout-info">
        <strong>No prediction for this file.</strong> {d.missing_requirement}
      </p>
      <p className="num text-sm muted">{d.rows.toLocaleString()} rows (first 200,000 shown) · {d.columns.length} columns · {d.numeric_columns} numeric. Units and time axis are not established, so charts use the row index.</p>
      {d.charts.map((c) => <TraceChart key={c.title} chart={c} height={200} />)}
    </div>
  );
}
