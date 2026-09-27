"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { GLOSSARY, type Term as GlossTerm } from "@/lib/glossary";

/** One glossary term with a click/focus definition. A quiet dotted underline signals "explained here". */
export function Term({ term, children }: { term: string; children?: React.ReactNode }) {
  const def = GLOSSARY.find((g) => g.term.toLowerCase() === term.toLowerCase());
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  // Keep the popover on screen: open leftwards when the term sits near the right edge.
  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setAlignRight(r.left + Math.min(352, window.innerWidth - 32) > window.innerWidth - 16);
  }, [open]);
  if (!def) return <>{children ?? term}</>;
  return (
    <span ref={ref} className="relative inline">
      <button ref={btn} type="button" className="term" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        {children ?? term}
      </button>
      {open && (
        <span id={id} role="note" className="term-pop" style={alignRight ? { right: 0 } : { left: 0 }}>
          <strong>{def.term}</strong>: {def.short}
          {def.why && <span className="mt-1 block muted">Why it matters: {def.why}</span>}
        </span>
      )}
    </span>
  );
}

// Longest terms first so "motor-current integral" wins over "current integral". Terms match as whole words, with an
// optional plural "s" ("cycles" → cycle), never inside another word.
const SORTED: GlossTerm[] = [...GLOSSARY].sort((a, b) => b.term.length - a.term.length);
const PATTERN = new RegExp(
  "(?<![\\w·-])(" + SORTED.map((g) => g.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "[\\s-]")).join("|") + ")(s?)(?![\\w²-])",
  "gi",
);

function lookup(p: string): GlossTerm | undefined {
  const k = p.toLowerCase();
  return SORTED.find((g) => g.term.toLowerCase() === k || g.term.toLowerCase() === k.replace(/-/g, " "));
}

/** Wrap glossary terms found in machine-generated text. Each term is glossed once per call (the first mention), so a
 *  paragraph never turns into a row of underlines. Terms of one or two characters (e.g. "K") only match as whole
 *  words; `plain` disables glossing (headings, compact rows). */
export default function Glossed({ text, subsystem, plain }: { text: string; subsystem?: string; plain?: boolean }) {
  if (plain || !text) return <>{text}</>;
  const out: React.ReactNode[] = [];
  const seen = new Set<string>();
  let last = 0;
  let k = 0;
  for (const m of Array.from(text.matchAll(PATTERN))) {
    const word = m[1];
    const plural = m[2];
    const def = lookup(word);
    const idx = m.index ?? 0;
    if (!def || seen.has(def.term) || (def.subsystem && subsystem && def.subsystem !== "all" && def.subsystem !== subsystem)) continue;
    // Short units ("K") need a space or bracket before them so they are not read out of e.g. "0.5 K" mid-word.
    if (def.term.length <= 2 && !/^$|[\s(]$/.test(text.slice(Math.max(0, idx - 1), idx))) continue;
    seen.add(def.term);
    if (idx > last) out.push(text.slice(last, idx));
    out.push(<Term key={k++} term={def.term}>{word + plural}</Term>);
    last = idx + word.length + plural.length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}
