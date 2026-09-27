"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiSend, apiUpload, downloadUrl, errorText } from "@/lib/api";
import {
  SUBSYSTEM_NAMES,
  type RunFile,
  type Subsystem,
  type QualityIssue,
} from "@/lib/types";
import {
  AlertBanner,
  Card,
  MetricTile,
  Skeleton,
  StatusBadge,
} from "@/components/engineering/Primitives";

const SUBS = Object.keys(SUBSYSTEM_NAMES) as Subsystem[];
type ValidatedFile = RunFile & {
  recognition: RunFile["recognition"] & {
    validation?: {
      rows: number;
      columns: number;
      coverage: string;
      sample_rate_hz?: number;
    };
    issues?: QualityIssue[];
  };
};

export default function UploadPage() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [run, setRun] = useState<string | null>(null);
  const [file, setFile] = useState<ValidatedFile | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  // Official test files are offered only where the server has them (not on a hosted copy).
  const [samples, setSamples] = useState<Subsystem[]>([]);
  useEffect(() => {
    apiGet<{ datasets: { subsystem: Subsystem; training_example: boolean }[] }>(
      "/api/v1/datasets",
    )
      .then((r) =>
        setSamples(
          r.datasets.filter((d) => !d.training_example).map((d) => d.subsystem),
        ),
      )
      .catch(() => setSamples([]));
  }, []);
  async function upload(files: FileList | File[]) {
    if (busy || !files.length) return;
    if (files.length > 1) {
      setError(
        "Choose one recording at a time. Each recording receives its own evidence and inspection report.",
      );
      return;
    }
    // FileList is live: copy before the input is cleared or any await occurs.
    const recording = files[0];
    setError("");
    setFile(null);
    setBusy("Validating recording…");
    try {
      const r = await apiSend<{ id: string }>("POST", "/api/v1/runs", {});
      setRun(r.id);
      const uploaded = await apiUpload<{ files: ValidatedFile[] }>(
        `/api/v1/runs/${r.id}/files`,
        [recording],
      );
      setFile(uploaded.files[0]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  async function interpret(field: "sheet" | "subsystem", value: string) {
    if (!file?.id || !run || !value) return;
    setError("");
    setBusy("Checking interpretation…");
    try {
      setFile(
        await apiSend<ValidatedFile>(
          "PATCH",
          `/api/v1/runs/${run}/interpretation`,
          { file_id: file.id, [field]: value },
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  async function analyze() {
    if (!run) return;
    setError("");
    setBusy("Starting analysis…");
    try {
      const r = await apiSend<{ runs: string[] }>(
        "POST",
        `/api/v1/runs/${run}/analyze`,
        { idempotency_key: run },
      );
      router.push(`/runs/${r.runs[0]}`);
    } catch (e) {
      setError(errorText(e));
      setBusy("");
    }
  }
  const rec = file?.recognition;
  const validation = rec?.validation;
  const blocked = !!file && !["ready", "awaiting_input"].includes(file.status);
  return (
    <div className="upload-workspace">
      <section
        className={`drop-zone ${drag ? "is-dragging" : ""}`}
        aria-label="Upload recording"
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          upload(e.dataTransfer.files);
        }}
      >
        <h1>Analyse a recording</h1>
        <p className="muted">
          Drop a data file here, or choose one from your computer.
        </p>
        <input
          ref={input}
          className="sr-only"
          type="file"
          aria-label="Recording file"
          accept=".csv,.xlsx,.txt"
          disabled={!!busy}
          onChange={(e) => {
            if (e.target.files) upload(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          className="btn btn-primary"
          disabled={!!busy}
          onClick={() => input.current?.click()}
        >
          {file ? "Choose another file" : "Choose file"}
        </button>
        <p className="text-sm muted">
          CSV for all four subsystems · Excel (.xlsx) also supported for ACV ·
          one recording at a time
        </p>
      </section>
      <ul className="sample-list" aria-label="Supported subsystems">
        {SUBS.map((sub) => (
          <li key={sub}>
            <span>{SUBSYSTEM_NAMES[sub]}</span>
            {samples.includes(sub) && (
              <a
                className="link text-sm"
                href={downloadUrl(`/api/v1/samples/${sub}`)}
                download
                aria-label={`Download ${SUBSYSTEM_NAMES[sub]} official test file`}
              >
                Download official test file
              </a>
            )}
          </li>
        ))}
      </ul>
      {samples.length > 0 && (
        <p className="sample-note">
          These are provided test inputs, not generated data. For the complete
          bundle, analyse all official test batches in Past analyses.
        </p>
      )}
      {error && (
        <AlertBanner error title="Could not complete this step">
          {error}
        </AlertBanner>
      )}
      {busy && <Skeleton label={busy} />}
      {file && (
        <Card id="validation">
          <div className="section-heading">
            <h2 className="font-semibold">File validation</h2>
            <StatusBadge
              condition={
                blocked
                  ? "Blocked"
                  : file.status === "ready"
                    ? "Ready"
                    : "Needs confirmation"
              }
            />
          </div>
          <p className="file-name mt-2">{file.original_name}</p>
          <div className="validation-controls">
            <label htmlFor="detected-subsystem">Detected subsystem</label>
            <select
              id="detected-subsystem"
              className="input"
              disabled={!!busy || !file.id}
              value={file.subsystem || rec?.subsystem || ""}
              onChange={(e) => interpret("subsystem", e.target.value)}
            >
              <option value="" disabled>
                Not recognised
              </option>
              {SUBS.map((sub) => (
                <option key={sub} value={sub}>
                  {SUBSYSTEM_NAMES[sub]}
                </option>
              ))}
            </select>
          </div>
          {rec?.needs && (
            <AlertBanner title="Confirm the source">
              <p>{rec.needs.question}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {rec.needs.options.map((value) => (
                  <button
                    className="btn"
                    key={value}
                    disabled={!!busy}
                    onClick={() => interpret(rec.needs!.field, value)}
                  >
                    {rec.needs!.field === "subsystem"
                      ? "Confirm SHM stress"
                      : value}
                  </button>
                ))}
              </div>
            </AlertBanner>
          )}
          {blocked && (
            <AlertBanner error title="Recording cannot be analysed">
              <p>{rec?.reason || file.error?.message}</p>
              <p className="mt-2">
                {rec?.suggestion ||
                  "Restore the required headers and data values using the sample format, then upload the corrected recording."}
              </p>
            </AlertBanner>
          )}
          {validation && (
            <>
              <dl className="metric-grid">
                <MetricTile
                  label="Parsed rows"
                  value={validation.rows.toLocaleString()}
                  unit="rows"
                />
                <MetricTile
                  label="Parsed columns"
                  value={validation.columns}
                  unit="columns"
                />
                <MetricTile
                  label="Sampling rate"
                  value={
                    validation.sample_rate_hz
                      ? Number(validation.sample_rate_hz.toPrecision(4))
                      : "Not supplied"
                  }
                  unit={validation.sample_rate_hz ? "Hz" : undefined}
                />
              </dl>
              <p className="text-sm">
                <span className="muted">Time / sample range</span>
                <br />
                <span className="num">{validation.coverage}</span>
              </p>
            </>
          )}
          {!!rec?.issues?.length && (
            <div className="mt-4">
              <AlertBanner title="Data quality and assumptions">
                <ul className="quality-list">
                  {rec.issues.map((issue, i) => (
                    <li key={i}>
                      <p>{issue.description}</p>
                      <p className="muted">
                        {issue.treatment}
                        {issue.next_step ? ` ${issue.next_step}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </AlertBanner>
            </div>
          )}
          {file.status === "ready" && (
            <div className="validation-footer">
              <p className="text-sm muted">
                Analysis uses the full recording. No model is trained on this
                upload.
              </p>
              <button
                className="btn btn-primary"
                disabled={!!busy}
                onClick={analyze}
              >
                Analyse recording
              </button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
