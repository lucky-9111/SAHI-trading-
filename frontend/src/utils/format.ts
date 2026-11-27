/** Display-only formatting. Amounts arrive from the backend as strings/numbers; no financial math happens here. */
export function inr(value: string | number | null | undefined, signed = false): string {
  const n = Number(value ?? 0);
  const s = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(n));
  const sign = n < 0 ? "-" : signed && n > 0 ? "+" : "";
  return `${sign}₹${s}`;
}

/** Plain number with Indian grouping and 2 decimals (no currency symbol). */
export function price(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
}

/** "+65.25 (0.25%)" style change text. */
export function changeText(change: string | number | null | undefined, pct: string | number | null | undefined): string {
  if (change === null || change === undefined || pct === null || pct === undefined) return "—";
  const c = Number(change);
  const sign = c > 0 ? "+" : "";
  return `${sign}${price(c)} (${Math.abs(Number(pct)).toFixed(2)}%)`;
}

export function pnlClass(value: string | number): string {
  const n = Number(value);
  return n > 0 ? "text-up" : n < 0 ? "text-down" : "text-slate-500";
}

/** Server times are UTC; some arrive without an offset ("2026-11-27T08:34:10"). Read those as UTC, show them in IST. */
export function parseTime(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
}
export function istTime(iso: string, opts: Intl.DateTimeFormatOptions): string {
  return parseTime(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", ...opts });
}
