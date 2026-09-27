"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, apiSend, downloadUrl, errorText } from "@/lib/api";
import { SUBSYSTEM_NAMES, type Subsystem } from "@/lib/types";
import { plural } from "@/lib/format";
import { EmptyState, ErrorNote, Loading, PageHeader } from "@/components/ui";
import BatchImport from "@/components/engineering/BatchImport";

type RunRow = {
  id: string; subsystem: Subsystem; subsystem_label: string; state: string; created: string; file_names: string[];
  file_count: number; review_total: number; reviewed_items: number; quality: string[]; versions: { model: string } | null; label?: string | null;
};

type Inventory = {
  expected: Partial<Record<Subsystem, number>>;
  candidates: Record<Subsystem, { id: string; created: string; file_count: number; file_names: string[]; matches_official_test: boolean }[]>;
};

const STATE_TEXT: Record<string, string> = {
  completed: "Completed", partial_failure: "Partly failed", failed: "Failed", cancelled: "Cancelled",
  interrupted: "Interrupted — rerun needed", queued: "Queued", running: "Running",
};

function Bundle() {
  const [inv, setInv] = useState<Inventory | null>(null);
  const [sel, setSel] = useState<Partial<Record<Subsystem, string>>>({});
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; errors?: string[]; link?: string; coverage?: Record<string, { status: string; rows: number; expected: number | null }> } | null>(null);
  useEffect(() => {
    apiGet<Inventory>("/api/v1/prediction_exports/inventory").then((r) => {
      setInv(r);
      const pre: Partial<Record<Subsystem, string>> = {};
      (Object.keys(r.candidates) as Subsystem[]).forEach((s) => {
        const m = r.candidates[s].find((c) => c.matches_official_test);
        if (m) pre[s] = m.id;
      });
      setSel(pre);
    }).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  }, []);
  async function build() {
    setMsg(null);
    try {
      const r = await apiSend<{ download: string; manifest: { coverage: Record<string, { status: string; rows: number; expected: number | null }> } }>(
        "POST", "/api/v1/exports", { kind: "bundle", runs: sel });
      setMsg({ ok: true, text: "predictions.zip is ready.", link: downloadUrl(r.download), coverage: r.manifest.coverage });
    } catch (e) {
      const err = e as { body?: { errors?: string[] } };
      setMsg({ ok: false, text: errorText(e), errors: err.body?.errors });
    }
  }
  if (!inv) return null;
  const subs: Subsystem[] = ["door", "acv", "rail", "shm"];
  const ready = subs.filter((x) => sel[x]).length;
  return (
    <details className="card p-4 md:p-5" aria-labelledby="sub-h" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer">
        <span id="sub-h" className="text-lg font-semibold">Export prediction bundle</span>
        <span className="ml-2 text-sm muted">· build predictions.zip from one analysis per subsystem ({ready} of 4 selected)</span>
      </summary>
      <div className="mt-3 space-y-3">
      <p className="max-w-prose text-sm muted">
        Builds <span className="mono">predictions.zip</span> with only the four official CSV files at its root. Coverage is checked
        against the provided official test inputs by filename and file fingerprint (SHA-256).
        Only complete, verified test batches can be selected; synthetic, training and modified
        files are excluded. Only selected subsystems are included.
      </p>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="data">
          <thead><tr><th>Subsystem</th><th>Analysis to include</th><th>Official test files</th></tr></thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s}>
                <td className="font-semibold">{SUBSYSTEM_NAMES[s]}</td>
                <td>
                  <select className="input w-full" value={sel[s] ?? ""}
                          onChange={(e) => setSel({ ...sel, [s]: e.target.value || undefined })} aria-label={`${SUBSYSTEM_NAMES[s]} analysis`}>
                    <option value="">Exclude from export</option>
                    {inv.candidates[s]?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {new Date(c.created).toLocaleString()} · {plural(c.file_count, "file")} · verified official inputs
                      </option>
                    ))}
                  </select>
                </td>
                <td className="num">{inv.expected[s] ?? "not found"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ready === 0 && <p className="text-sm muted">No verified batches yet. Use Analyse an official test batch below, then return here.</p>}
      <button className="btn btn-primary" disabled={ready === 0} onClick={build}>Build predictions.zip</button>
      {msg && (
        <div role={msg.ok ? "status" : "alert"} className={`callout text-sm ${msg.ok ? "callout-info" : "callout-error"}`}>
          <p className="font-semibold">{msg.text}</p>
          {msg.errors && <ul className="ml-5 list-disc">{msg.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
          {msg.coverage && (
            <ul className="ml-5 list-disc text-ink">
              {Object.entries(msg.coverage).map(([k, v]) => <li key={k}>{SUBSYSTEM_NAMES[k as Subsystem]}: {v.status}{v.rows !== undefined ? ` — ${plural(v.rows, "row")}` : ""}</li>)}
            </ul>
          )}
          {msg.link && <a className="btn btn-primary mt-2" href={msg.link}>Download predictions.zip</a>}
        </div>
      )}
      </div>
    </details>
  );
}

export default function History() {
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => apiGet<{ runs: RunRow[] }>("/api/v1/runs", { limit: 100 }).then((r) => setRuns(r.runs)).catch((e) => setError(errorText(e)));
  useEffect(() => { load(); }, []);
  async function del(id: string) {
    if (!confirm("Delete this analysis, its stored uploads and results? Files read in place from your computer are not touched.")) return;
    try {
      await apiSend("DELETE", `/api/v1/runs/${id}`);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <div className="space-y-6">
      <PageHeader
        title="Past analyses"
        description="Saved recordings and their diagnostic evidence. Results describe historical data, not live asset condition."
        actions={<Link className="btn btn-primary" href="/analyze">New analysis</Link>}
      />
      <Bundle />
      <BatchImport />
      {error && <ErrorNote>{error}</ErrorNote>}
      {runs === null ? <Loading /> : runs.length === 0 ? (
        <EmptyState title="No analyses yet."><Link className="link" href="/analyze">Start a new analysis</Link>.</EmptyState>
      ) : (
        <div className="card overflow-x-auto">
          <table className="data">
            <thead><tr><th>Analysis</th><th>Files</th><th>Created</th><th>Uncertain</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link className="font-semibold hover:underline" href={`/runs/${r.id}`}>{r.subsystem_label}</Link>
                    <div className="mono text-xs muted">{r.versions?.model}</div>
                    {r.state !== "completed" && <span className={`tag mt-1 ${r.state === "failed" || r.state === "partial_failure" || r.state === "interrupted" ? "tag-fault" : "tag-neutral"}`}>{STATE_TEXT[r.state] ?? r.state}</span>}
                    {r.quality.includes("usable_with_limitations") && <div className="text-xs text-plan">Data limitations</div>}
                  </td>
                  <td className="text-sm">
                    <span className="mono">{r.file_names[0]}</span>
                    {r.file_count > 1 && <span className="muted"> + {r.file_count - 1} more</span>}
                  </td>
                  <td className="num whitespace-nowrap text-sm">{new Date(r.created).toLocaleString()}</td>
                  <td className="whitespace-nowrap">
                    {r.review_total
                      ? <span className="tag tag-review" title="Findings whose evidence is unusual; the result stands but should be looked at">{plural(r.review_total, "finding")}</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <Link className="btn btn-sm" href={`/runs/${r.id}`}>Open</Link>{" "}
                    <button className="btn btn-ghost btn-sm ml-1 text-act" onClick={() => del(r.id)} aria-label={`Delete analysis ${r.id}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
