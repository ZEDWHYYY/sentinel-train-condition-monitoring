"use client";
import { downloadUrl } from "@/lib/api";
import { SUBSYSTEM_NAMES, type Item, type ResultRow, type Run } from "@/lib/types";
import { Card } from "./Primitives";

// The frozen model's output in the official vocabulary: exactly what the
// subsystem's *_predictions.csv (and predictions.zip) contains.
export const PREDICTION_FILES = {
  door: "door_predictions.csv",
  acv: "acv_predictions.csv",
  rail: "rail_predictions.csv",
  shm: "shm_predictions.csv",
} as const;

const RAIL_GLOSS: Record<string, string> = {
  Normal: "No corrugation detected on either rail.",
  "Side I": "Corrugation on the Side I rail (axle-box positions 1, 3, 5, 7).",
  "Side II": "Corrugation on the Side II rail (axle-box positions 2, 4, 6, 8).",
};

const byName = (a: ResultRow, b: ResultRow) =>
  a.file.original_name.localeCompare(b.file.original_name, undefined, {
    numeric: true,
  });

const damage = (v: Item["prediction"]) =>
  typeof v === "number" ? String(Number(v.toPrecision(4))) : "—";

function Label({ value }: { value: string }) {
  const tone = value === "Normal" ? "ok" : "fault";
  return <span className={`tag tag-${tone}`}>{value}</span>;
}

function Unavailable({ row }: { row: ResultRow }) {
  return (
    <p className="text-sm">
      No prediction for {row.file.original_name}:{" "}
      {row.headline || "the recording does not support a usable estimate."}
    </p>
  );
}

function DoorSegments({ row }: { row: ResultRow }) {
  const items = row.items;
  const abnormal = items.filter((i) => i.prediction !== "Normal").length;
  return (
    <>
      <p className="prediction-value">
        {abnormal} of {items.length} door movements predicted{" "}
        <span className="whitespace-nowrap">Abnormal resistance</span>
      </p>
      <p className="text-sm muted">
        {items.length - abnormal} Normal. Each movement is one detected
        open/close cycle in the continuous stream; its start, end and label
        form one row of the CSV.
      </p>
      <div
        className="prediction-table"
        tabIndex={0}
        role="region"
        aria-label="Predicted door movements"
      >
        <table className="data">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Start time</th>
              <th scope="col">End time</th>
              <th scope="col">Duration</th>
              <th scope="col">Prediction</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, k) => {
              const f = it.features as { duration_s?: number } | undefined;
              return (
                <tr key={it.id}>
                  <td className="num">{k + 1}</td>
                  <td className="num">{String(it.start_time)}</td>
                  <td className="num">{String(it.end_time)}</td>
                  <td className="num">
                    {f?.duration_s !== undefined
                      ? `${f.duration_s.toFixed(2)} s`
                      : "—"}
                  </td>
                  <td>
                    <Label value={String(it.prediction)} />
                    {it.review_reasons.length > 0 && (
                      <span className="tag tag-review ml-2">Review</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AcvRanking({ row }: { row: ResultRow }) {
  const item = row.items[0];
  const ranked = (item.ranked_cars as string[] | undefined) ?? [];
  const margin = item.margin_K as number | null | undefined;
  return (
    <>
      <p className="prediction-value">Car {ranked[0]}</p>
      <p className="text-sm muted">
        Most likely to have the refrigerant leak. Every car in the file, from
        most to least likely:
      </p>
      <ol className="ranking" aria-label="Cars ranked from most to least likely">
        {ranked.map((car, k) => (
          <li key={car}>
            <span className="ranking-position num">{k + 1}</span> Car {car}
          </li>
        ))}
      </ol>
      {typeof margin === "number" && margin < 0.5 && (
        <p className="text-sm mt-3">
          The top two cars differ by only {margin.toFixed(2)} K, below one
          sensor step. The full ranking is still included in the export, but
          treat the top pick as uncertain.
        </p>
      )}
    </>
  );
}

function BatchTable({
  sub,
  rows,
  selected,
  onSelect,
}: {
  sub: "acv" | "rail" | "shm";
  rows: ResultRow[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const heading =
    sub === "shm"
      ? "Predicted damage"
      : sub === "acv"
        ? "Ranked cars (most likely first)"
        : "Prediction";
  return (
    <div className="prediction-table">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Recording</th>
            <th scope="col">{heading}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const p = r.items[0]?.prediction ?? null;
            return (
              <tr key={r.id} className={r.id === selected ? "selected" : ""}>
                <td>
                  <button
                    className="link"
                    aria-current={r.id === selected ? "true" : undefined}
                    onClick={() => onSelect(r.id)}
                  >
                    {r.file.original_name}
                  </button>
                </td>
                <td className="num">
                  {!r.available || p === null ? (
                    "Unavailable"
                  ) : sub === "rail" ? (
                    <Label value={String(p)} />
                  ) : sub === "shm" ? (
                    damage(p)
                  ) : (
                    String(p).split("|").join(" › ")
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function PredictionPanel({
  run,
  rows,
  selected,
  onSelect,
}: {
  run: Run;
  rows: ResultRow[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const sub = run.subsystem;
  if (!sub || !rows.length) return null;
  const sorted = [...rows].sort(byName);
  const single = sorted.length === 1 ? sorted[0] : null;
  const ready =
    ["completed", "partial_failure"].includes(run.state) &&
    sorted.every((r) => r.available);
  let body;
  if (sub === "door") {
    const row = sorted.find((r) => r.id === selected) ?? sorted[0];
    body = row.available ? <DoorSegments row={row} /> : <Unavailable row={row} />;
  } else if (single) {
    const p = single.items[0]?.prediction ?? null;
    body = !single.available || p === null ? (
      <Unavailable row={single} />
    ) : sub === "acv" ? (
      <AcvRanking row={single} />
    ) : sub === "rail" ? (
      <>
        <p className="prediction-value">
          <Label value={String(p)} />
        </p>
        <p className="text-sm muted">{RAIL_GLOSS[String(p)]}</p>
      </>
    ) : (
      <>
        <p className="prediction-value num">{damage(p)}</p>
        <p className="text-sm muted">
          Predicted cumulative fatigue damage for this segment (dimensionless,
          Miner&apos;s-rule scale). The CSV keeps full precision.
        </p>
      </>
    );
  } else {
    const counts: Record<string, number> = {};
    for (const r of sorted) {
      const p = r.items[0]?.prediction;
      if (sub === "rail" && typeof p === "string")
        counts[p] = (counts[p] ?? 0) + 1;
    }
    body = (
      <>
        <p className="prediction-value">
          {sub === "rail"
            ? ["Normal", "Side I", "Side II"]
                .map((label) => `${counts[label] ?? 0} ${label}`)
                .join(" · ")
            : `${sorted.length} recordings`}
        </p>
        <p className="text-sm muted">
          One row per recording, as in the CSV. Select a recording to see its
          evidence below.
        </p>
        <BatchTable
          sub={sub}
          rows={sorted}
          selected={selected}
          onSelect={onSelect}
        />
      </>
    );
  }
  return (
    <Card id="prediction" className="prediction-card">
      <div className="section-heading">
        <div>
          <h2 className="section-label">
            Model prediction
            {sorted.length > 1 &&
              ` · ${SUBSYSTEM_NAMES[sub]} · ${sorted.length} recordings`}
          </h2>
          <p className="text-sm muted mt-1">
            Frozen model output in the official format. The inspection advice
            below never changes it.
          </p>
        </div>
        {ready ? (
          <a
            className="btn btn-primary"
            href={downloadUrl(`/api/v1/runs/${run.id}/predictions.csv`)}
            download
          >
            Download prediction CSV
          </a>
        ) : (
          <p className="text-sm muted">
            The CSV is available once every recording has a prediction.
          </p>
        )}
      </div>
      <div className="mt-4">{body}</div>
      <p className="text-sm muted mt-4">
        File: <span className="mono">{PREDICTION_FILES[sub]}</span> · written
        by the same serializer as the command-line predictor and
        predictions.zip.
      </p>
    </Card>
  );
}
