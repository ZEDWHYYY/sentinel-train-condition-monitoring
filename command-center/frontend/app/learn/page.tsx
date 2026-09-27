"use client";

import { useEffect, useState } from "react";
import { Term } from "@/components/Glossed";
import { AcvDiagram, DoorDiagram, RailPositionsDiagram, ShmDiagram } from "@/components/learn/Diagrams";
import { apiGet, errorText } from "@/lib/api";
import { GLOSSARY } from "@/lib/glossary";
import { SUBSYSTEM_NAMES, type Subsystem } from "@/lib/types";
import { ErrorNote, PageHeader } from "@/components/ui";

type Ref = {
  door: { class_ranges: Record<string, Record<string, [number, number]>>; class_counts: Record<string, Record<string, number>>; cutoffs: Record<string, number>;
    relative_rule: { baseline_percentile: number; min_cycles_per_direction: number; directions: Record<string, { ratio_cutoff: number; normal_ratio_max: number; abnormal_ratio_min: number }> } | null;
    gap_threshold_s: number; version: string } | null;
  acv: { params: Record<string, number>; cooling_modes: string[]; score_definition: string; version: string } | null;
  rail: { normal_side_rms_median: number; threshold: number; review_band: [number, number]; bands_hz: [number, number][]; side_established: boolean; version: string } | null;
  shm: { feature_ranges: Record<string, [number, number]>; gate: number; m: number; formula: string; validation: { score: number; mape: number; mape_low_half: number; mape_high_half: number };
    training_damage: { min: number; median: number; max: number; n: number } | null; version: string } | null;
};
type Learn = { reference: Ref; maintenance_map: Record<Subsystem, { finding: string; decision: string; instead_of: string }>; checklists: Record<Subsystem, string[]> };

const f0 = (v: number) => Math.round(v).toLocaleString();

export default function LearnPage() {
  const [d, setD] = useState<Learn | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiGet<Learn>("/api/v1/learn").then(setD).catch((e) => setError(errorText(e))); }, []);
  const r = d?.reference;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Learn: what the train is telling us"
        description={<>For engineers new to these subsystems: what the equipment does, what the signals mean, what normal looks like, how SENTINEL decides, and how to read the charts. Numbers come from the frozen models, so they match what the app uses. <span className="term cursor-default">Dotted-underlined</span> words open a short definition.</>}
      >
        <nav aria-label="On this page" className="mt-3 flex flex-wrap gap-2 text-sm">
          {(["door", "acv", "rail", "shm"] as Subsystem[]).map((x) => <a key={x} className="btn btn-sm" href={`#${x}`}>{SUBSYSTEM_NAMES[x]}</a>)}
          <a className="btn btn-sm" href="#reading">Reading the app</a>
          <a className="btn btn-sm" href="#glossary">Glossary</a>
        </nav>
      </PageHeader>
      {error && <ErrorNote>{error}</ErrorNote>}

      {/* ---------------------------------------------------------------- Door */}
      <section id="door" className="card scroll-mt-20 space-y-3 p-5 md:p-6 [&>p]:max-w-prose">
        <h2 className="text-xl font-semibold">Door — abnormal resistance</h2>
        <DoorDiagram />
        <p><strong>What the equipment does.</strong> A saloon door is a leaf on rollers in a slide rail, driven by a small DC motor. The controller
          logs the motor's current and voltage 50 times a second, the <Term term="back electromotive force">back-EMF</Term> (a proxy for speed), the{" "}
          <Term term="door leaf position">leaf position</Term>, and the limit switches <Term term="DCSR">DCSR</Term>/<Term term="DCSL">DCSL</Term> (closed) and{" "}
          <Term term="DLSR">DLSR</Term>/<Term term="DLSL">DLSL</Term> (locked).</p>
        <p><strong>What goes wrong.</strong> Grit in the rail, a rubbing rubber strip or a bent leaf add friction. The motor has to push harder for the same
          travel, so it draws more current for longer. Left alone this leads to jamming and motor overload. The recording shows the extra effort, not the cause.</p>
        <p><strong>How SENTINEL decides.</strong> The continuous recording is cut into <Term term="cycle">cycles</Term> wherever the rows pause for more than
          {r?.door ? ` ${r.door.gap_threshold_s} s` : " 1 s"} (in training, rows inside a cycle are 0.02 s apart and cycles are ≥ 10 s apart). For each cycle it works out
          the direction from the commands, motion flags, close switches and position trend, then sums the current over the movement — the{" "}
          <Term term="motor-current integral">motor-current integral</Term>. Opening and closing are judged separately because they naturally differ.
          {r?.door?.relative_rule && (
            <> The decision is <em>relative to this door's own level</em>: the cycle's integral is divided by the recording's <Term term="baseline">baseline</Term>{" "}
            ({r.door.relative_rule.baseline_percentile}th percentile of that direction's cycles) and compared with a frozen ratio
            ({Object.entries(r.door.relative_rule.directions).map(([k, v]) => `${k} ${v.ratio_cutoff.toFixed(3)}×`).join(", ")}). This is why a door that
            simply draws a bit more current than the training door is not flagged wholesale — the Info Kit warns that a uniform threshold across doors gives false alarms.</>
          )}
        </p>
        {r?.door && (
          <div>
            <p><strong>What normal looks like (training door).</strong></p>
            <div className="mt-1 w-fit max-w-full overflow-x-auto rounded-lg border border-line"><table className="data">
              <thead><tr><th>Movement</th><th>Normal integral (mA·s)</th><th>Abnormal integral (mA·s)</th><th>Cycles</th>{r.door.relative_rule && <th>Normal ratio ≤ / Abnormal ratio ≥</th>}</tr></thead>
              <tbody>
                {(["Open", "Close"] as const).map((op) => (
                  <tr key={op}>
                    <td>{op}</td>
                    <td className="num whitespace-nowrap">{f0(r.door!.class_ranges[op].Normal[0])}–{f0(r.door!.class_ranges[op].Normal[1])}</td>
                    <td className="num whitespace-nowrap">{f0(r.door!.class_ranges[op]["Abnormal resistance"][0])}–{f0(r.door!.class_ranges[op]["Abnormal resistance"][1])}</td>
                    <td className="num whitespace-nowrap">{r.door!.class_counts[op].Normal} / {r.door!.class_counts[op]["Abnormal resistance"]}</td>
                    {r.door!.relative_rule && <td className="num whitespace-nowrap">{r.door!.relative_rule.directions[op].normal_ratio_max.toFixed(3)}× / {r.door!.relative_rule.directions[op].abnormal_ratio_min.toFixed(3)}×</td>}
                  </tr>
                ))}
              </tbody>
            </table></div>
            <p className="mt-1 text-sm muted">Peak current and duration did not separate the classes; the integral did. A normal opening lasts about 2.8 s and a closing about 3.7 s.</p>
          </div>
        )}
        <p><strong>Reading the chart.</strong> The current trace of a cycle is drawn over the grey band of normal training cycles (10th–90th percentile) aligned at
          movement start. A healthy cycle has a start-up peak, a low plateau while the leaf travels, and an end-of-travel rise. Extra resistance lifts the plateau
          or stretches it. The band is a range of normal cycles, not a confidence interval.</p>
        <Decision d={d} s="door" />
      </section>

      {/* ---------------------------------------------------------------- ACV */}
      <section id="acv" className="card scroll-mt-20 space-y-3 p-5 md:p-6 [&>p]:max-w-prose">
        <h2 className="text-xl font-semibold">ACV — refrigerant leak localisation</h2>
        <AcvDiagram />
        <p><strong>What the equipment does.</strong> Each of the 8 cars has its own air-conditioning unit: a compressor circulates refrigerant that absorbs heat in
          the cabin and dumps it outside. The train logs, every 30 s per car, the cabin (indoor) temperature, the <Term term="cooling target">cooling target</Term>,
          the <Term term="running mode">running mode</Term> and whether the data is valid.</p>
        <p><strong>What goes wrong.</strong> A <Term term="refrigerant leak">leak</Term> reduces the charge. The unit still runs, but moves less heat, so under load the
          cabin sits warmer than it should — and warmer than the neighbouring cars, which share the same weather, passengers and schedule.</p>
        <p><strong>How SENTINEL decides.</strong> For every timestamp when a car is in <Term term="active cooling">active cooling</Term> and{" "}
          <Term term="settled cooling">settled</Term>, it takes the car's cabin temperature minus the median of the other cooling cars — the{" "}
          <Term term="peer residual">peer residual</Term>. The mean over the recording ranks the cars, warmest first. No weights are fitted; the rule is the same for
          every case. {r?.acv && <>Parameters: settle {r.acv.params.settle_rows} samples ({r.acv.params.settle_rows * r.acv.params.row_seconds / 60} min), at least {r.acv.params.min_peers} peers,
          at least {r.acv.params.min_valid_rows} valid samples ({r.acv.params.min_valid_rows * r.acv.params.row_seconds / 3600} h), review when the top two are within {r.acv.params.tie_margin_K} K.</>}</p>
        <p><strong>What normal looks like.</strong> Cars track each other within about ±0.2 K most of the time; sensors report in 0.5 <Term term="K">K</Term> steps.
          In the six training cases the faulty car sat between +0.2 K and +1.5 K above its peers on average. Short 0 °C readings are sensor dropouts, not cold cabins.
          A margin below one sensor step between the top two cars is weak evidence — the app says so rather than pointing at one car.</p>
        <p><strong>Reading the chart.</strong> Blue is the chosen car's cabin temperature, grey the median of the other cars, orange its own target; shaded periods are when the
          car was cooling. Look for the blue line riding above the grey during the shaded periods, especially in the hottest hours.</p>
        <Decision d={d} s="acv" />
      </section>

      {/* ---------------------------------------------------------------- Rail */}
      <section id="rail" className="card scroll-mt-20 space-y-3 p-5 md:p-6 [&>p]:max-w-prose">
        <h2 className="text-xl font-semibold">Rail corrugation — which rail is wavy</h2>
        <RailPositionsDiagram />
        <p><strong>What the equipment does.</strong> Every wheel's <Term term="axle box">axle box</Term> carries an accelerometer (vibration) and a{" "}
          <Term term="shock">shock</Term> channel, sampled 10,000 times a second for one second per file: 8 cars × 8 positions × 2 = 128 channels plus a{" "}
          <Term term="speed pulse">speed pulse</Term>. Positions 1, 3, 5, 7 run on <Term term="Side I">Side I</Term>; 2, 4, 6, 8 on <Term term="Side II">Side II</Term>.</p>
        <p><strong>What goes wrong.</strong> <Term term="rail corrugation">Corrugation</Term> is periodic wear on the rail head. Wheels running over it are excited at a
          frequency set by wavelength and speed, so the axle boxes shake much harder than on smooth rail, with energy concentrated in a frequency band. It roars,
          hurts ride comfort and loads fasteners and running gear; the fix is grinding or milling.</p>
        <p><strong>How SENTINEL decides.</strong> Per channel it computes <Term term="RMS">RMS</Term>, peak, <Term term="kurtosis">kurtosis</Term>,{" "}
          <Term term="crest factor">crest factor</Term> and band energies from the <Term term="Welch PSD">spectrum</Term>{r?.rail && <> ({r.rail.bands_hz.map((b) => `${b[0]}–${b[1]}`).join(", ")} Hz)</>}.
          These are pooled per side. A Random Forest first decides <em>corrugation or not</em> (the <Term term="fault-detection score">fault-detection score</Term>,
          threshold {r?.rail?.threshold ?? 0.5}); a second model then decides the side from Side I − Side II contrasts.
          {r?.rail?.side_established === false && " Side discrimination did not pass validation, so the side follows a documented policy and every fault is flagged."}{" "}
          Speed is deliberately <em>not</em> a feature: in the training data every fault file was recorded at higher speed than half of the normal files, so a model
          using speed would learn the acquisition, not the rail.</p>
        {r?.rail && <p><strong>What normal looks like.</strong> Median axle-box vibration RMS on a normal file is about {r.rail.normal_side_rms_median.toFixed(2)} m/s²
          on both sides; corrugation files run several times higher — and on <em>both</em> sides, because the vibration crosses the axle, which is why side is decided by
          contrast features rather than by the taller bar. Scores between {r.rail.review_band[0]} and {r.rail.review_band[1]} are flagged for review.</p>}
        <p><strong>Reading the charts.</strong> The car-by-side bar chart shows vibration level per car (blue Side I, orange Side II). The spectrum view draws one channel's
          energy by frequency over the grey band of normal files: corrugation shows as a hump standing out of the band. Track position is not in the data.</p>
        <Decision d={d} s="rail" />
      </section>

      {/* ---------------------------------------------------------------- SHM */}
      <section id="shm" className="card scroll-mt-20 space-y-3 p-5 md:p-6 [&>p]:max-w-prose">
        <h2 className="text-xl font-semibold">SHM — cumulative fatigue damage</h2>
        <ShmDiagram />
        <p><strong>What the equipment does.</strong> Strain gauges on the carbody or bogie frame record dynamic stress continuously; the system saves equal-length
          segments as files (581,120 samples each; the sampling rate and stress unit are not documented).</p>
        <p><strong>What goes wrong.</strong> Metal fails by fatigue: many load swings, each harmless alone, accumulate microscopic damage. <Term term="Miner's rule">Miner's rule</Term>{" "}
          says each <Term term="stress cycle">cycle</Term> uses up a fraction of the life; when the sum reaches 1 the design criterion is met. Big swings cost
          disproportionately more — under the <Term term="S–N curve">S–N curve</Term> used here, doubling a cycle's <Term term="cycle range">range</Term> multiplies its damage by 2⁵ = 32.</p>
        <p><strong>How SENTINEL decides.</strong> It extracts turning points, ignores wiggles smaller than the <Term term="gate">gate</Term>{r?.shm && <> ({r.shm.gate} stress units)</>},
          counts cycles with <Term term="rainflow">rainflow</Term> counting (ASTM E1049), and sums c · n · range^m with m{r?.shm && <> = {r.shm.m}</>} and c fitted to the training
          labels (the material's S–N constants were not supplied, so this is a data-fitted surrogate). Leave-one-file-out validation:
          {r?.shm && <> score {r.shm.validation.score.toFixed(3)} (average error {(r.shm.validation.mape * 100).toFixed(1)} %; {(r.shm.validation.mape_low_half * 100).toFixed(1)} % on the low-damage half).</>}</p>
        {r?.shm?.training_damage && <p><strong>What normal looks like.</strong> All training segments come from healthy structures. Their damage values ran from
          {" "}{r.shm.training_damage.min.toFixed(3)} to {r.shm.training_damage.max.toFixed(3)} (median {r.shm.training_damage.median.toFixed(3)}), with peak-to-peak stress
          {" "}{r.shm.feature_ranges.p2p[0].toFixed(0)}–{r.shm.feature_ranges.p2p[1].toFixed(0)} and RMS {r.shm.feature_ranges.rms[0].toFixed(1)}–{r.shm.feature_ranges.rms[1].toFixed(1)}.
          Values outside these ranges mean the model is extrapolating and the app says so.</p>}
        <p><strong>Reading the charts.</strong> The stress trace shows the whole segment with every peak preserved; the cycle histogram (log scale) shows that most cycles are small and a
          handful are large — those few carry most of the damage. File numbers are arbitrary, so the per-file bar chart is <em>not</em> a trend over time.</p>
        <Decision d={d} s="shm" />
      </section>

      <section id="reading" className="card scroll-mt-20 space-y-2 p-5 md:p-6">
        <h2 className="text-xl font-semibold">Reading the app</h2>
        <ul className="ml-5 max-w-prose list-disc space-y-1.5">
          <li><strong>Model prediction</strong> is the frozen model&apos;s output in the official format: exactly what goes into the subsystem&apos;s CSV and <code>predictions.zip</code>. <strong>Download prediction CSV</strong> saves it.</li>
          <li><strong>Inspection advice</strong> (Normal / Watch / Action required) is derived from the prediction and its measured evidence by a separately versioned, uncalibrated policy. It suggests what to check and never changes the prediction.</li>
          <li><strong>Recommended action</strong> and <strong>Other likely actions</strong> list checks with their evidence: value, unit, time window and reference. The support score (0–1) shows how strongly the evidence points at that check; it is not a probability.</li>
          <li><strong>Review</strong> (<Term term="review suggested">review suggested</Term>) means the evidence is unusual (near a decision line, outside the <Term term="training range">training range</Term>, a data issue). Each reason comes with a concrete next check.</li>
          <li><strong>Historical, not live.</strong> Every result describes a recording that was uploaded; the app does not know the current state of the train, and the files carry no train or asset identity.</li>
        </ul>
      </section>

      <section id="glossary" className="card scroll-mt-20 p-5 md:p-6">
        <h2 className="text-xl font-semibold">Glossary</h2>
        <dl className="mt-3 grid gap-x-8 gap-y-3 md:grid-cols-2">
          {[...GLOSSARY].sort((a, b) => a.term.localeCompare(b.term)).map((g) => (
            <div key={g.term}>
              <dt className="font-semibold">{g.term} <span className="text-xs font-normal muted">{g.subsystem && g.subsystem !== "all" ? SUBSYSTEM_NAMES[g.subsystem] : ""}</span></dt>
              <dd className="text-sm">{g.short}{g.why && <span className="muted"> {g.why}</span>}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function Decision({ d, s }: { d: Learn | null; s: Subsystem }) {
  if (!d) return null;
  const m = d.maintenance_map[s];
  return (
    <details className="panel p-3 text-sm">
      <summary className="cursor-pointer font-semibold">Maintenance decision this supports, and the technician's checklist</summary>
      <p className="mt-2"><strong>{m.finding}</strong> → {m.decision} <span className="muted">Instead of: {m.instead_of}.</span></p>
      <ol className="ml-5 mt-2 list-decimal">{d.checklists[s].map((c, i) => <li key={i}>{c}</li>)}</ol>
      <p className="mt-2 text-xs muted">General condition-monitoring practice written for this prototype; not an LTA policy document.</p>
    </details>
  );
}
