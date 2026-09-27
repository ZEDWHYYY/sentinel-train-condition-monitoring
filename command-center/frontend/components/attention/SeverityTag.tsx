import { SEVERITY_META, type Severity } from "@/lib/types";

const GLYPH: Record<Severity, string> = { high: "●", medium: "▲", low: "◆", info: "○" };

/** Colour plus text plus shape, so severity never relies on colour alone. */
export default function SeverityTag({ severity, size = "md" }: { severity: Severity; size?: "sm" | "md" | "lg" }) {
  const m = SEVERITY_META[severity] ?? SEVERITY_META.info;
  const cls = size === "lg" ? "text-base px-3 py-1" : size === "sm" ? "text-xs" : "";
  return (
    <span className={`tag ${m.cls} ${cls}`} title={m.hint}>
      <span aria-hidden>{GLYPH[severity]}</span> {m.label}
    </span>
  );
}
