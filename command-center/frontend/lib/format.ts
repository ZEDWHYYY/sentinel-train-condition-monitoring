const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Natural order: Test2.csv before Test10.csv. */
export function natural(a: string, b: string): number {
  return collator.compare(a, b);
}

/** Door native timestamp "2023-7-5-0-0-3-760" -> "00:00:03.760" (recorded clock). */
export function doorClock(native: string): string {
  const p = native.split("-");
  if (p.length !== 7) return native;
  const two = (s: string) => s.padStart(2, "0");
  return `${two(p[3])}:${two(p[4])}:${two(p[5])}.${p[6].padStart(3, "0")}`;
}

/** Door native timestamp -> "2023-07-05". */
export function doorDate(native: string): string {
  const p = native.split("-");
  if (p.length !== 7) return native;
  return `${p[0]}-${p[1].padStart(2, "0")}-${p[2].padStart(2, "0")}`;
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function localTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Seconds -> "m:ss" for time axes. */
export function minSec(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}
