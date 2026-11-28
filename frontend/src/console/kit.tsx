import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../services/api";
import { istTime } from "../utils/format";

/** Fetch `path` now and every `ms` (paused while the tab is hidden). */
export function usePoll<T>(path: string | null, ms = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const alive = useRef(true);
  const load = useCallback(() => {
    if (!path) return Promise.resolve();
    return api<T>(path).then((d) => { if (alive.current) { setData(d); setError(""); } }).catch((e) => { if (alive.current) setError(e.message); });
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    const id = ms ? setInterval(() => { if (!document.hidden) load(); }, ms) : undefined;
    return () => { alive.current = false; if (id) clearInterval(id); };
  }, [load, ms]);
  return { data, error, reload: load, setData };
}

export function Page({ title, badge, right, sub, children }: { title: ReactNode; badge?: ReactNode; right?: ReactNode; sub?: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[24px] lg:text-[28px] font-semibold tracking-tight">{title}</h1>{badge}
        <div className="flex-1" />{right}
      </div>
      {sub && <p className="-mt-3 text-[13.5px] text-muted max-w-[900px]">{sub}</p>}
      {children}
    </div>
  );
}

export function Panel({ title, right, children, className = "", pad = true }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card bg-white ${className}`}>
      {(title || right) && <div className="flex flex-wrap items-center gap-3 px-5 pt-4 pb-2"><div className="text-[16px] font-semibold flex items-center gap-2">{title}</div><div className="flex-1" />{right}</div>}
      <div className={pad ? "px-5 pb-4 pt-1" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, tone = "" }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="card px-4 py-3 min-w-0">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`text-[22px] font-semibold mt-1 truncate ${tone}`}>{value}</div>
    </div>
  );
}

const TONE: Record<string, string> = {
  ok: "bg-buybg text-buy", success: "bg-buybg text-buy", warn: "bg-[#fff1d6] text-[#8a5a00]", warning: "bg-[#fff1d6] text-[#8a5a00]",
  fail: "bg-sellbg text-sell", error: "bg-sellbg text-sell", info: "bg-[#e6f0ff] text-[#1f4fa8]", muted: "bg-soft text-muted", dark: "bg-ink text-white",
};
export function Badge({ tone = "muted", children }: { tone?: string; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11.5px] font-semibold uppercase tracking-wide whitespace-nowrap ${TONE[tone] ?? TONE.muted}`}>{children}</span>;
}
export const statusLabel = (s: string) => ({ ok: "OK", warn: "Check", fail: "Problem" } as Record<string, string>)[s] ?? s;

export function Table({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-5">
      <table className="w-full text-[13.5px]">
        <thead><tr className="text-left text-muted">{head.map((h, i) => <th key={i} className="font-medium px-5 py-2 whitespace-nowrap">{h}</th>)}</tr></thead>
        <tbody className="[&>tr]:border-t [&>tr]:border-line [&_td]:px-5 [&_td]:py-2.5 [&_td]:align-middle">{children}</tbody>
      </table>
      {empty}
    </div>
  );
}

export function Btn({ children, onClick, tone = "ghost", disabled, title }: { children: ReactNode; onClick?: () => void; tone?: "ghost" | "danger" | "primary"; disabled?: boolean; title?: string }) {
  const cls = tone === "primary" ? "bg-ink text-white hover:bg-black border-ink" : tone === "danger" ? "border-sell/40 text-sell hover:bg-sellbg/50" : "border-line hover:bg-soft";
  return <button title={title} disabled={disabled} onClick={onClick} className={`rounded-full border px-3.5 py-1.5 text-[13px] whitespace-nowrap transition-colors disabled:opacity-40 ${cls}`}>{children}</button>;
}

export function ErrorBox({ text }: { text: string }) {
  return text ? <div role="alert" className="rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] text-sell">{text}</div> : null;
}

export function ago(s: number | null | undefined) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const when = (iso: string | null | undefined) =>
  iso ? istTime(iso, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—";

/** Download rows as a CSV file (built in the browser from data already on screen). */
export function downloadCsv(name: string, rows: (string | number | boolean | null | undefined)[][]) {
  const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const blob = new Blob([rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Simple bar chart for the 30-day sign-in charts. */
export function Bars({ values, color, labels }: { values: number[]; color: string; labels: [string, string] }) {
  const max = Math.max(1, ...values);
  return (
    <div>
      <div className="flex items-end gap-[3px] h-[110px]">
        {values.map((v, i) => <div key={i} title={String(v)} className="flex-1 rounded-t-sm" style={{ height: `${Math.max(2, (v / max) * 100)}%`, background: color, opacity: v ? 1 : 0.25 }} />)}
      </div>
      <div className="flex justify-between text-[11.5px] text-muted mt-1"><span>{labels[0]}</span><span>{labels[1]}</span></div>
    </div>
  );
}
