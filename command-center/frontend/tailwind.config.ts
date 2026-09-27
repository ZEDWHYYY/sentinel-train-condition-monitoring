import type { Config } from "tailwindcss";

// Quiet operations palette. Colours are CSS variables defined in app/globals.css (single source of truth).
// Blue `accent` means "interactive" only; status colours are separate: act (red), plan (amber), watch (violet),
// ok (green), neutral (grey). `fault` and `review` are kept as aliases of act/plan for older class names.
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  // Built from data at runtime (e.g. `opcard-${severity}`), so the scanner cannot see them.
  safelist: [{ pattern: /^(opcard|sev|sev-bar)-(high|medium|low|info)$/ }],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: v("surface"),
        subtle: v("subtle"),
        ink: v("ink"),
        "ink-2": v("ink-2"),
        "ink-3": v("ink-3"),
        line: v("line"),
        "line-strong": v("line-strong"),
        accent: v("accent"),
        "accent-weak": v("accent-weak"),
        act: v("act"),
        "act-weak": v("act-weak"),
        plan: v("plan"),
        "plan-weak": v("plan-weak"),
        watch: v("watch"),
        "watch-weak": v("watch-weak"),
        ok: v("ok"),
        "ok-weak": v("ok-weak"),
        fault: v("act"),
        review: v("plan"),
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      maxWidth: {
        prose: "72ch",
      },
    },
  },
  plugins: [],
};
export default config;
