"use client";
import type { ReactNode } from "react";
import TraceChart, { fmt } from "@/components/charts/TraceChart";
import BarChart from "@/components/charts/BarChart";
import type { Chart } from "@/lib/types";

export type Evidence = {
  signal: string;
  value: number;
  unit: string;
  window: string;
  chart_id: string;
  reference?: string;
};
export type Action = {
  id: string;
  instruction: string;
  confidence: number;
  confidence_basis: string;
  urgency: string;
  reason: string;
  evidence: Evidence[];
};
export type Diagnosis = {
  condition: string;
  explanation: string;
  confidence_note: string;
  policy_version: string;
  primary: Action;
  alternatives: Action[];
};
export type DiagnosticChart = Chart & { id: string };
export const supportScore = (value: number) =>
  value > 0 && value < 0.01 ? value.toPrecision(2) : value.toFixed(2);

export function Card({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`card engineering-card ${className}`}>
      {children}
    </section>
  );
}
export function StatusBadge({ condition }: { condition: string }) {
  const tone =
    condition === "Normal" || condition === "Ready"
      ? "ok"
      : condition === "Watch"
        ? "review"
        : condition === "Action required" || condition === "Blocked"
          ? "fault"
          : "neutral";
  return (
    <span className={`tag tag-${tone}`} data-testid="condition">
      {condition}
    </span>
  );
}
export function AlertBanner({
  children,
  title = "Check the recording",
  error = false,
}: {
  children: ReactNode;
  title?: string;
  error?: boolean;
}) {
  return (
    <div
      className={`alert-banner ${error ? "alert-error" : ""}`}
      role={error ? "alert" : "note"}
    >
      <p className="font-semibold">{title}</p>
      <div className="mt-1 text-sm">{children}</div>
    </div>
  );
}
export function MetricTile({
  label,
  value,
  unit,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
}) {
  return (
    <div className="metric-tile">
      <dt>{label}</dt>
      <dd className="num">
        {value}
        {unit && <span className="metric-unit"> {unit}</span>}
      </dd>
    </div>
  );
}
export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return (
    <ul className="evidence-list">
      {evidence.map((e, i) => (
        <li key={i}>
          <div className="evidence-value">
            <a className="link" href={`#${e.chart_id}`}>
              {e.signal}
            </a>
            <span className="num font-semibold">
              {fmt(e.value, 5)} <span className="font-normal">{e.unit}</span>
            </span>
          </div>
          <p className="text-sm muted">{e.window}</p>
          {e.reference && <p className="text-sm muted">{e.reference}</p>}
        </li>
      ))}
    </ul>
  );
}
export function Confidence({ action }: { action: Action }) {
  return (
    <details className="confidence text-sm">
      <summary>
        Evidence confidence{" "}
        <strong className="num">{supportScore(action.confidence)} / 1</strong>
      </summary>
      <p className="mt-2 muted">{action.confidence_basis}</p>
      <p className="mt-1 muted">
        Uncalibrated support for this check, not a fault or repair probability.
      </p>
    </details>
  );
}
export function ActionCard({ action }: { action: Action }) {
  return (
    <Card className="primary-action">
      <div className="section-label">Recommended action</div>
      <h2 className="action-title">{action.instruction}</h2>
      <div className="action-meta">
        <span>
          <span className="muted">Urgency</span> · {action.urgency}
        </span>
        <Confidence action={action} />
      </div>
      <h3 className="font-semibold mt-5">Why this check</h3>
      <EvidenceList evidence={action.evidence} />
    </Card>
  );
}
export function ChartPanel({ chart }: { chart: DiagnosticChart }) {
  return (
    <Card id={chart.id} className="chart-panel">
      {chart.kind === "bar" || chart.kind === "grouped_bar" ? (
        <BarChart chart={chart} />
      ) : (
        <TraceChart chart={chart} height={250} />
      )}
    </Card>
  );
}
export function Skeleton({ label }: { label: string }) {
  return (
    <Card>
      <div role="status" aria-live="polite">
        <p className="font-semibold">{label}</p>
        <p className="text-sm muted mt-1">
          Checking the full recording with the frozen diagnostic method.
        </p>
      </div>
      <div aria-hidden className="skeleton-stack">
        <div />
        <div />
        <div />
      </div>
    </Card>
  );
}

type Channel = {
  name: string;
  kind?: string;
  unit?: string;
  min?: number;
  median?: number;
  max?: number;
  mean?: number;
  std?: number;
  missing?: number;
};
export function SignalStatistics({ channels }: { channels: Channel[] }) {
  const unit = (c: Channel) =>
    c.unit ||
    (c.kind === "state" || c.name === "Rotating speed"
      ? "state (0/1)"
      : c.name.includes("(mA)")
        ? "mA"
        : c.name.includes("(10mV)")
          ? "10 mV"
          : c.name.includes("(.1s)")
            ? "0.1 s"
            : "raw units (undocumented)");
  return (
    <>
      <h3 className="font-semibold mt-5">Signal statistics</h3>
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Signal</th>
              <th scope="col">Unit</th>
              <th scope="col">Minimum</th>
              <th scope="col">Median</th>
              <th scope="col">Maximum</th>
              <th scope="col">Missing samples</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{unit(c)}</td>
                <td>{fmt(c.min)}</td>
                <td>{fmt(c.median)}</td>
                <td>{fmt(c.max)}</td>
                <td>{c.missing ?? "Not recorded"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
