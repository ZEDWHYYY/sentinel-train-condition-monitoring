/** Schematic diagrams for the Learn page. Hand-drawn SVG (no external images): they show the mechanism the text
 *  describes — where the sensors sit and which measurement the model uses — not photographs of real faults. */

export function RailPositionsDiagram() {
  const cars = [1, 2, 3, 4, 5, 6, 7, 8];
  const W = 820, carW = 82, carH = 46, y0 = 52;
  return (
    <figure className="my-3">
      <svg viewBox={`0 0 ${W} 176`} className="w-full max-w-4xl rounded-lg border border-line bg-white" role="img"
           aria-label="Eight cars seen from above. On each car, axle-box positions 1, 3, 5, 7 lie on the Side I rail and 2, 4, 6, 8 on the Side II rail.">
        <text x={10} y={14} fontSize="12" fill="#4b5563">Train seen from above · Side I rail (top) · Side II rail (bottom)</text>
        <line x1={10} x2={752} y1={y0 - 8} y2={y0 - 8} stroke="#1f5fbf" strokeWidth={3} />
        <line x1={10} x2={752} y1={y0 + carH + 8} y2={y0 + carH + 8} stroke="#c2410c" strokeWidth={3} />
        <text x={760} y={y0 - 4} fontSize="11" fill="#1f5fbf" fontWeight={700}>Side I</text>
        <text x={760} y={y0 + carH + 12} fontSize="11" fill="#c2410c" fontWeight={700}>Side II</text>
        {cars.map((c, i) => {
          const x = 14 + i * (carW + 10);
          return (
            <g key={c}>
              <rect x={x} y={y0} width={carW} height={carH} rx={6} fill="#f8fafc" stroke="#9ca3af" />
              <text x={x + carW / 2} y={y0 + carH / 2 + 4} fontSize="12" textAnchor="middle" fill="#1b1f24">Car {c}</text>
              {[1, 3, 5, 7].map((p, k) => (
                <g key={p}>
                  <circle cx={x + 12 + k * 19} cy={y0 - 8} r={5} fill="#1f5fbf" />
                  <text x={x + 12 + k * 19} y={y0 - 16} fontSize="9" textAnchor="middle" fill="#1f5fbf">{p}</text>
                </g>
              ))}
              {[2, 4, 6, 8].map((p, k) => (
                <g key={p}>
                  <circle cx={x + 12 + k * 19} cy={y0 + carH + 8} r={5} fill="#c2410c" />
                  <text x={x + 12 + k * 19} y={y0 + carH + 26} fontSize="9" textAnchor="middle" fill="#c2410c">{p}</text>
                </g>
              ))}
            </g>
          );
        })}
        <text x={10} y={150} fontSize="11" fill="#4b5563">● = axle box with a vibration + shock accelerometer (64 per train, 2 channels each = 128 columns).</text>
        <text x={10} y={166} fontSize="11" fill="#4b5563">Speed pulse = column 1.</text>
      </svg>
      <figcaption className="mt-1 text-xs muted">Schematic drawn for this app from the Rail Info Kit's description (odd positions = Side I, even = Side II); not to scale.</figcaption>
    </figure>
  );
}

export function DoorDiagram() {
  return (
    <figure className="my-3">
      <svg viewBox="0 0 760 212" className="w-full max-w-4xl rounded-lg border border-line bg-white" role="img"
           aria-label="A sliding door leaf on rollers in a slide rail driven by a motor; a foreign object or a rubbing seal adds resistance, so the motor current rises for the same travel.">
        <text x={20} y={30} fontSize="11" fill="#4b5563">slide rail</text>
        <rect x={20} y={38} width={400} height={10} fill="#9ca3af" />
        <rect x={60} y={50} width={150} height={72} rx={4} fill="#eef4ff" stroke="#1f5fbf" />
        <text x={135} y={90} fontSize="12" textAnchor="middle" fill="#1b1f24">door leaf</text>
        <circle cx={80} cy={46} r={6} fill="#1f5fbf" /><circle cx={190} cy={46} r={6} fill="#1f5fbf" />
        <text x={20} y={142} fontSize="11" fill="#4b5563">rollers · position sensor (700 = closed, 0 = open)</text>
        <rect x={300} y={42} width={10} height={14} fill="#b42318" />
        <text x={305} y={76} fontSize="11" textAnchor="middle" fill="#b42318">grit / jammed seal</text>
        <text x={305} y={90} fontSize="11" textAnchor="middle" fill="#b42318">= extra resistance</text>
        <path d="M420 86 H436" stroke="#9a6700" strokeWidth={2} markerEnd="url(#arr)" />
        <rect x={442} y={60} width={112} height={52} rx={6} fill="#fff8e6" stroke="#9a6700" />
        <text x={498} y={82} fontSize="12" textAnchor="middle" fill="#1b1f24">DC motor</text>
        <text x={498} y={99} fontSize="10" textAnchor="middle" fill="#4b5563">current · voltage</text>
        <rect x={576} y={38} width={170} height={104} rx={6} fill="#fff" stroke="#d9dee5" />
        <text x={661} y={56} fontSize="10" textAnchor="middle" fill="#4b5563">motor current, one movement</text>
        <polyline fill="none" stroke="#6b7280" strokeWidth={1.5} points="590,128 602,86 614,106 660,108 704,106 724,86 736,84" />
        <polyline fill="none" stroke="#b42318" strokeWidth={1.5} points="590,128 602,84 614,98 660,96 704,94 724,78 736,76" />
        <text x={576} y={158} fontSize="10" fill="#4b5563">grey = normal</text>
        <text x={576} y={172} fontSize="10" fill="#b42318">red = abnormal resistance</text>
        <text x={576} y={186} fontSize="10" fill="#b42318">(higher plateau, larger integral)</text>
        <text x={20} y={188} fontSize="11" fill="#4b5563">Limit switches DCSR/DCSL (closed) and DLSR/DLSL (locked) mark the end positions.</text>
        <text x={20} y={204} fontSize="11" fill="#4b5563">The model uses the area under the current curve.</text>
        <defs><marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9a6700" /></marker></defs>
      </svg>
      <figcaption className="mt-1 text-xs muted">Schematic drawn for this app; the real mechanism differs in detail. The curves are sketches of the shapes seen in the training data.</figcaption>
    </figure>
  );
}

export function AcvDiagram() {
  return (
    <figure className="my-3">
      <svg viewBox="0 0 760 166" className="w-full max-w-4xl rounded-lg border border-line bg-white" role="img"
           aria-label="Eight cars each with an air-conditioning unit; every car reports cabin temperature, cooling target and running mode; the leaking car's cabin sits warmer than its neighbours during cooling.">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((c, i) => {
          const x = 14 + i * 92;
          const leak = c === 3;
          return (
            <g key={c}>
              <rect x={x} y={40} width={82} height={50} rx={6} fill={leak ? "#fef3f2" : "#f8fafc"} stroke={leak ? "#b42318" : "#9ca3af"} />
              <text x={x + 41} y={60} fontSize="12" textAnchor="middle" fill="#1b1f24">Car 0{c}</text>
              <text x={x + 41} y={78} fontSize="11" textAnchor="middle" fill={leak ? "#b42318" : "#4b5563"}>{leak ? "24.5 °C (+1 K)" : "23.5 °C"}</text>
              <rect x={x + 26} y={26} width={30} height={12} rx={3} fill={leak ? "#b42318" : "#1f5fbf"} />
              <text x={x + 41} y={35} fontSize="8" textAnchor="middle" fill="#fff">ACV</text>
            </g>
          );
        })}
        <text x={14} y={112} fontSize="11" fill="#4b5563">Same weather, same passengers, same target: a car whose cabin stays warmer than the median</text>
        <text x={14} y={127} fontSize="11" fill="#4b5563">of the others while cooling is the leak candidate.</text>
        <text x={14} y={150} fontSize="11" fill="#4b5563">Each car logs every 30 s: cabin temperature · cooling target · running mode · data valid.</text>
      </svg>
      <figcaption className="mt-1 text-xs muted">Illustration with made-up temperatures to show the comparison; real cases differ by 0.2–1.5 K.</figcaption>
    </figure>
  );
}

export function ShmDiagram() {
  return (
    <figure className="my-3">
      <svg viewBox="0 0 760 150" className="w-full max-w-4xl rounded-lg border border-line bg-white" role="img"
           aria-label="A stress history is cut into cycles by rainflow counting; each cycle's range is raised to the power m and summed to give the damage.">
        <text x={14} y={22} fontSize="11" fill="#4b5563">stress signal → turning points → rainflow cycles (range r, count n) → damage D = c · Σ n · r^m</text>
        <polyline fill="none" stroke="#1f5fbf" strokeWidth={1.5} points="14,90 40,60 60,100 80,70 100,110 130,40 160,120 190,75 210,95 240,55 270,105 300,80" />
        <text x={150} y={140} fontSize="11" textAnchor="middle" fill="#4b5563">stress over time (one segment = 581,120 samples)</text>
        <g transform="translate(340,0)">
          {[["small", 30, "#9ca3af", 8], ["medium", 60, "#6b7280", 20], ["large", 100, "#b42318", 35]].map(([name, h, col, w], i) => (
            <g key={String(name)}>
              <rect x={i * 90} y={120 - Number(h)} width={Number(w)} height={Number(h)} fill={String(col)} />
              <text x={i * 90 + Number(w) / 2} y={135} fontSize="10" textAnchor="middle" fill="#4b5563">{name} r</text>
            </g>
          ))}
          <text x={135} y={44} fontSize="11" textAnchor="middle" fill="#4b5563">cycle range r → damage share r^5</text>
        </g>
        <text x={620} y={70} fontSize="11" fill="#4b5563">doubling r</text>
        <text x={620} y={86} fontSize="11" fill="#b42318" fontWeight={700}>× 32 damage</text>
        <text x={620} y={110} fontSize="11" fill="#4b5563">D = 1 = design</text>
        <text x={620} y={124} fontSize="11" fill="#4b5563">failure criterion</text>
      </svg>
      <figcaption className="mt-1 text-xs muted">Schematic; bar widths are illustrative. m = 5 is the exponent fitted on the training labels.</figcaption>
    </figure>
  );
}
