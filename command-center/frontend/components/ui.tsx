"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Every page opens the same way: optional eyebrow, a title, one line saying what the page is for, and actions. */
export function PageHeader({ eyebrow, title, description, actions, children }: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-[28rem]">
        {eyebrow && <div className="mb-1 text-sm muted">{eyebrow}</div>}
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-prose muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

const TONE: Record<string, string> = { act: "text-act", plan: "text-plan", watch: "text-watch", ok: "text-ok", neutral: "" };

/** A single figure with a label. Used for counts at the top of pages; `onClick` turns it into a filter toggle. */
export function Stat({ label, value, tone = "neutral", pressed, onClick, hint }: {
  label: string;
  value: ReactNode;
  tone?: "act" | "plan" | "watch" | "ok" | "neutral";
  pressed?: boolean;
  onClick?: () => void;
  hint?: string;
}) {
  const inner = (
    <>
      <div className="text-sm muted">{label}</div>
      <div className={`num text-2xl font-bold leading-tight ${TONE[tone]}`}>{value}</div>
    </>
  );
  if (!onClick) return <div className="card min-w-[7rem] px-4 py-2.5" title={hint}>{inner}</div>;
  return (
    <button type="button" onClick={onClick} aria-pressed={!!pressed} title={hint}
            className={`card min-w-[7rem] px-4 py-2.5 text-left transition-colors hover:border-ink-3 ${pressed ? "border-accent ring-1 ring-accent" : ""}`}>
      {inner}
    </button>
  );
}

/** A titled block inside a page. */
export function Section({ title, description, actions, children, className = "", id }: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`space-y-3 ${className}`} aria-label={typeof title === "string" ? title : undefined}>
      {(title || actions) && (
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            {title && <h2 className="text-lg font-semibold">{title}</h2>}
            {description && <p className="text-sm muted">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/** A button that opens a small menu; closes on Escape, outside click, or choosing an item. */
export function Menu({ label, children, primary, align = "right" }: {
  label: ReactNode;
  children: (close: () => void) => ReactNode;
  primary?: boolean;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button ref={btn} type="button" className={`btn ${primary ? "btn-primary" : ""}`} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)}>
        {label}
        <svg aria-hidden width="12" height="12" viewBox="0 0 12 12" className={`transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className={`card absolute z-20 mt-1 w-72 space-y-1 p-2 shadow-lg ${align === "right" ? "right-0" : "left-0"}`}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

/** Chevron used by expandable rows. */
export function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`}>
      <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-sm muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <p role="alert" className="callout callout-error">{children}</p>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p role="status" className="py-6 text-sm muted">{label}</p>;
}
