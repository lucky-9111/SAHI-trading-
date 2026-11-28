import { useEffect, useState } from "react";
import { api } from "../services/api";
import { istTime } from "./format";

/** Market status comes from the backend (exchange calendar + server clock); the browser clock is never used to decide it. */
export interface MarketSession {
  exchange: string; state: "OPEN" | "PRE_OPEN" | "POST_CLOSE" | "CLOSED" | "WEEKEND" | "HOLIDAY"; label: string; is_open: boolean;
  special: boolean; note: string; session_start: string | null; session_end: string | null; next_open: string | null; server_time: string;
}
interface Sessions { server_time: string; exchanges: MarketSession[] }

const POLL_MS = 30000;
let current: Sessions | null = null;
const listeners = new Set<(s: Sessions | null) => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function load() {
  api<Sessions>("/api/market/sessions").then((s) => { current = s; listeners.forEach((f) => f(s)); }).catch(() => {});
}

/** One shared poll (every 30 s) for the whole app. `exchange` picks one row (NFO / BFO / CDS fall back to their cash exchange). */
export function useMarketStatus(exchange = "NSE"): MarketSession | null {
  const [s, setS] = useState<Sessions | null>(current);
  useEffect(() => {
    listeners.add(setS);
    if (!timer) { load(); timer = setInterval(load, POLL_MS); }
    return () => {
      listeners.delete(setS);
      if (!listeners.size && timer) { clearInterval(timer); timer = null; }
    };
  }, []);
  const ex = exchange.toUpperCase();
  const rows = s?.exchanges ?? [];
  return rows.find((r) => r.exchange === ex) ?? rows.find((r) => r.exchange === ({ BFO: "BSE", CDS: "NSE" } as Record<string, string>)[ex]) ?? rows[0] ?? null;
}

export function refreshMarketStatus() { load(); }

/** "Opens Mon 30 Nov, 09:15" / "Closes 15:30" */
export function sessionHint(m: MarketSession): string {
  if (m.is_open && m.session_end) return `Closes ${istTime(m.session_end, { hour: "2-digit", minute: "2-digit", hour12: false })}`;
  if (m.next_open) return `Opens ${istTime(m.next_open, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })}`;
  return "";
}
