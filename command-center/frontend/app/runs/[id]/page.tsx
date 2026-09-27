"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, downloadUrl, errorText } from "@/lib/api";
import {
  SUBSYSTEM_NAMES,
  type Run,
  type ResultRow,
  type FullResult,
} from "@/lib/types";
import {
  ActionCard,
  AlertBanner,
  Card,
  ChartPanel,
  Confidence,
  EvidenceList,
  MetricTile,
  SignalStatistics,
  supportScore,
  Skeleton,
  StatusBadge,
  type Diagnosis,
  type DiagnosticChart,
} from "@/components/engineering/Primitives";
import PredictionPanel from "@/components/engineering/PredictionPanel";

type DetailedResult = FullResult & {
  payload: FullResult["payload"] & {
    diagnosis?: Diagnosis;
    preview?: { columns: string[]; rows: (number | string | null)[][] };
  };
};
export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<Run | null>(null);
  const [options, setOptions] = useState<ResultRow[]>([]);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<DetailedResult | null>(null);
  const [charts, setCharts] = useState<DiagnosticChart[]>([]);
  const [error, setError] = useState("");
  const [chartError, setChartError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setRun(null);
    setError("");
    setResult(null);
    setOptions([]);
    setSelected("");
    async function poll() {
      try {
        const r = await apiGet<Run>(`/api/v1/runs/${id}`);
        if (cancelled) return;
        setRun(r);
        if (["queued", "running"].includes(r.state)) {
          timer = setTimeout(poll, 600);
          return;
        }
        if (r.state === "draft") {
          setError(
            "This recording has not been analysed. Upload it again to validate and start a new analysis.",
          );
          return;
        }
        const rows = await apiGet<{ results: ResultRow[] }>(
          `/api/v1/runs/${id}/results`,
          { limit: 500 },
        );
        if (cancelled) return;
        setOptions(rows.results);
        setSelected(rows.results[0]?.id || "");
        if (!rows.results.length)
          setError(
            r.error?.message ||
              r.files.find((f) => f.error)?.error?.message ||
              `Analysis ${r.state}. Upload a complete supported recording and try again.`,
          );
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, attempt]);
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setResult(null);
    setCharts([]);
    setChartError("");
    apiGet<DetailedResult>(`/api/v1/results/${selected}`)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        if (r.payload.diagnosis && r.payload.available)
          apiGet<{ charts: DiagnosticChart[] }>(
            `/api/v1/results/${selected}/diagnostic-charts`,
          )
            .then((c) => {
              if (!cancelled) setCharts(c.charts);
            })
            .catch((e) => {
              if (!cancelled) setChartError(errorText(e));
            });
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);
  const d = result?.payload.diagnosis;
  const p = result?.payload.profile;
  const batch = options.length > 1;
  const prediction = run && (
    <PredictionPanel
      run={run}
      rows={options}
      selected={selected}
      onSelect={setSelected}
    />
  );
  return (
    <div className="results-workspace">
      <div className="result-navigation">
        <Link className="link text-sm" href="/history">
          Past analyses
        </Link>
        <Link className="btn" href="/analyze">
          Upload another file / switch subsystem
        </Link>
      </div>
      {error && (
        <AlertBanner error title="Analysis could not be displayed">
          <p>{error}</p>
          <button className="btn mt-3" onClick={() => setAttempt((v) => v + 1)}>
            Try again
          </button>
        </AlertBanner>
      )}
      {!error && !result && (
        <Skeleton label={run?.stage || "Loading analysis…"} />
      )}
      {run?.state === "partial_failure" && (
        <AlertBanner title="Partial analysis">
          Some files could not be analysed. The results below cover only
          completed recordings.
        </AlertBanner>
      )}
      {batch && prediction}
      {batch && (
        <label className="validation-controls">
          Recording
          <select
            className="input"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {options.map((r) => (
              <option key={r.id} value={r.id}>
                {r.file.original_name}
              </option>
            ))}
          </select>
        </label>
      )}
      {result && (
        <>
          <header className="result-heading">
            <p className="file-name muted text-sm">
              {result.file.original_name}
            </p>
            <h1>{SUBSYSTEM_NAMES[result.subsystem]}</h1>
          </header>
          {!batch && prediction}
          <section className="advice-heading" aria-labelledby="advice-title">
            <div className="section-heading">
              <h2 id="advice-title" className="section-label">
                Inspection advice
              </h2>
              <StatusBadge condition={d?.condition || "Unavailable"} />
            </div>
            <p className="mt-2">
              {d?.explanation ||
                result.payload.unavailable_reason ||
                "This saved result predates the evidence-ranked policy. Re-upload the source recording to create a current report."}
            </p>
          </section>
          {result.payload.quality_state === "usable_with_limitations" && (
            <p className="text-sm muted">
              Partial / limited data:{" "}
              <a className="link" href="#data-details">
                review acquisition warnings and assumptions
              </a>{" "}
              before acting.
            </p>
          )}
          {d ? (
            <>
              <ActionCard action={d.primary} />
              <Card>
                <div className="section-heading">
                  <h2 className="font-semibold">Other likely actions</h2>
                  <span className="text-sm muted">
                    Ranked by evidence support
                  </span>
                </div>
                <ol className="alternative-list">
                  {d.alternatives.map((a, i) => (
                    <li key={a.id}>
                      <details>
                        <summary>
                          <span className="alternative-rank num">{i + 1}</span>
                          <span className="alternative-copy">
                            <strong>{a.instruction}</strong>
                            <span>{a.reason}</span>
                          </span>
                          <span className="num alternative-score">
                            {supportScore(a.confidence)} / 1<span>support</span>
                          </span>
                        </summary>
                        <div className="alternative-detail">
                          <Confidence action={a} />
                          <EvidenceList evidence={a.evidence} />
                        </div>
                      </details>
                    </li>
                  ))}
                </ol>
                <p className="text-sm muted mt-3">{d.confidence_note}</p>
              </Card>
              <section aria-labelledby="charts-heading" className="space-y-4">
                <h2 id="charts-heading" className="section-label">
                  Supporting evidence
                </h2>
                {chartError && (
                  <AlertBanner error title="Charts could not be loaded">
                    {chartError} The saved findings remain available.
                  </AlertBanner>
                )}
                {!charts.length && !chartError && result.payload.available && (
                  <Skeleton label="Preparing evidence charts…" />
                )}
                {charts.map((c) => (
                  <ChartPanel key={`${selected}-${c.id}`} chart={c} />
                ))}
              </section>
            </>
          ) : (
            <AlertBanner title="No current recommendation">
              No confidence or action has been invented for this result.{" "}
              <Link className="link" href="/analyze">
                Upload the source recording
              </Link>{" "}
              to analyse it with the current policy.
            </AlertBanner>
          )}
          <Card id="data-details">
            <details className="data-details">
              <summary>
                Data details{" "}
                <span className="muted text-sm">
                  · statistics, quality and parsed preview
                </span>
              </summary>
              {p && (
                <>
                  <dl className="metric-grid">
                    <MetricTile
                      label="Rows analysed"
                      value={p.rows.toLocaleString()}
                      unit="rows"
                    />
                    <MetricTile
                      label="Channels / columns"
                      value={p.columns}
                      unit="columns"
                    />
                    <MetricTile
                      label="Sampling rate"
                      value={
                        p.sample_rate_hz
                          ? Number(p.sample_rate_hz.toPrecision(4))
                          : "Not supplied"
                      }
                      unit={p.sample_rate_hz ? "Hz" : undefined}
                    />
                  </dl>
                  <p className="text-sm">
                    <span className="muted">Coverage</span> · {p.coverage}
                  </p>
                  <p className="text-sm muted">{p.sample_rate_source}</p>
                </>
              )}
              {!!result.payload.issues.length && (
                <div className="mt-4">
                  <AlertBanner title="Data quality and assumptions">
                    <ul className="quality-list">
                      {result.payload.issues.map((q, i) => (
                        <li key={i}>
                          <p>{q.description}</p>
                          <p className="muted">
                            {q.treatment} {q.effect} {q.next_step}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </AlertBanner>
                </div>
              )}
              {!result.payload.issues.length && (
                <p className="text-sm muted mt-3">
                  No data-quality issues found by the implemented checks.
                </p>
              )}
              {Array.isArray(p?.channels) && (
                <SignalStatistics channels={p.channels} />
              )}
              <h3 className="font-semibold mt-5">
                Parsed preview · first{" "}
                {result.payload.preview?.rows.length || 0} rows
              </h3>
              {result.payload.preview && (
                <div className="table-scroll">
                  <table className="data">
                    <thead>
                      <tr>
                        {result.payload.preview.columns.map((c) => (
                          <th key={c} scope="col">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.payload.preview.rows.map((row, i) => (
                        <tr key={i}>
                          {row.map((v, j) => (
                            <td key={j} className="num">
                              {v === null
                                ? "Missing"
                                : typeof v === "number"
                                  ? Number(v.toPrecision(6)).toLocaleString()
                                  : v}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <dl className="provenance text-sm">
                <dt>Frozen method</dt>
                <dd>{result.payload.method_name}</dd>
                <dt>Model version</dt>
                <dd>{result.payload.model_version}</dd>
                <dt>Advisory policy</dt>
                <dd>{d?.policy_version || "Legacy result"}</dd>
                <dt>Input SHA-256</dt>
                <dd className="num">{result.file.sha256}</dd>
              </dl>
              <p className="text-sm muted mt-3">
                This is a historical recording, not a live condition or a safety
                release.{" "}
                <Link className="link" href="/method">
                  Methods and validation limits
                </Link>
              </p>
            </details>
          </Card>
          {d && (
            <div className="export-row">
              <div>
                <h2 className="font-semibold">Keep the findings</h2>
                <p className="text-sm muted">
                  Actions, confidence basis, values, units and source windows.
                </p>
              </div>
              <a
                className="btn"
                href={downloadUrl(`/api/v1/results/${result.id}/findings.csv`)}
                download
              >
                Download findings CSV
              </a>
            </div>
          )}
        </>
      )}
    </div>
  );
}
