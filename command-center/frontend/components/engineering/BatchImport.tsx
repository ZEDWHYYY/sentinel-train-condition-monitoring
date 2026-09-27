"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiSend, errorText } from "@/lib/api";
import type { RunFile, Subsystem } from "@/lib/types";
import { AlertBanner, Skeleton } from "./Primitives";

type Dataset = {
  label: string;
  path: string;
  subsystem: Subsystem;
  files: number;
  training_example: boolean;
};
export default function BatchImport() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [run, setRun] = useState("");
  const [files, setFiles] = useState<RunFile[]>([]);
  async function add(d: Dataset) {
    setBusy("Validating the complete batch…");
    setError("");
    setFiles([]);
    try {
      const r = await apiSend<{ id: string }>("POST", "/api/v1/runs", {
        subsystem: d.subsystem,
      });
      setRun(r.id);
      const f = await apiSend<{ files: RunFile[] }>(
        "POST",
        `/api/v1/runs/${r.id}/local-path`,
        { path: d.path },
      );
      setFiles(f.files);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  async function analyze() {
    setBusy("Starting batch analysis…");
    try {
      const r = await apiSend<{ runs: string[] }>(
        "POST",
        `/api/v1/runs/${run}/analyze`,
        {},
      );
      router.push(`/runs/${r.runs[0]}`);
    } catch (e) {
      setError(errorText(e));
      setBusy("");
    }
  }
  return (
    <details
      className="card engineering-card"
      onToggle={(e) => {
        if (e.currentTarget.open && !datasets.length)
          apiGet<{ datasets: Dataset[] }>("/api/v1/datasets")
            .then((r) =>
              setDatasets(r.datasets.filter((d) => !d.training_example)),
            )
            .catch((e) => setError(errorText(e)));
      }}
    >
      <summary className="font-semibold">
        Analyse an official test batch{" "}
        <span className="text-sm muted">· local files, read-only</span>
      </summary>
      <p className="text-sm muted mt-3">
        For bundle coverage, analyse a complete subsystem test set in one
        run. Files are read in place; originals are never changed.
      </p>
      <div className="flex flex-wrap gap-2 mt-4">
        {datasets.map((d) => (
          <button
            className="btn"
            disabled={!!busy}
            key={d.path}
            onClick={() => add(d)}
          >
            {d.label} · {d.files} files
          </button>
        ))}
      </div>
      {!datasets.length && !error && (
        <p className="text-sm muted mt-3">
          No local official datasets have been discovered.
        </p>
      )}
      {busy && (
        <div className="mt-4">
          <Skeleton label={busy} />
        </div>
      )}
      {error && (
        <div className="mt-4">
          <AlertBanner error>{error}</AlertBanner>
        </div>
      )}
      {!!files.length && (
        <div className="mt-4">
          <p>
            {files.filter((f) => f.status === "ready").length} of {files.length}{" "}
            files ready.
          </p>
          {files
            .filter((f) => f.status !== "ready")
            .map((f) => (
              <p className="text-sm text-act" key={f.id}>
                {f.original_name}: {f.recognition?.reason}
              </p>
            ))}
          <button
            className="btn btn-primary mt-3"
            disabled={!!busy || files.some((f) => f.status !== "ready")}
            onClick={analyze}
          >
            Analyse batch
          </button>
        </div>
      )}
    </details>
  );
}
