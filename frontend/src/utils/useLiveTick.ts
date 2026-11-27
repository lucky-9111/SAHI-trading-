import { useEffect, useState } from "react";
import { api } from "../services/api";

export interface LiveTick { ltp: number; age: number }
interface TicksResponse { ticks: Record<string, LiveTick>; feed: { connected: boolean; error: string | null } }

/** Polls the backend's in-memory tick store (fed by Angel's websocket) about once a second. No broker call is made per poll.
 *  `fresh` is true while the latest tick is less than 20 s old; a tick is never invented. */
export function useLiveTick(exchange: string | undefined, token: string | undefined, ms = 1000) {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  useEffect(() => {
    setTick(null);
    if (!exchange || !token) return;
    let stop = false;
    const load = () => {
      if (document.hidden) return;
      api<TicksResponse>(`/api/market/ticks?s=${encodeURIComponent(`${exchange}:${token}`)}`)
        .then((r) => { if (!stop) { setTick(r.ticks[`${exchange}:${token}`] ?? null); setConnected(r.feed.connected); } })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, ms);
    return () => { stop = true; clearInterval(t); };
  }, [exchange, token, ms]);
  const fresh = !!tick && tick.age < 20;
  return { tick, fresh, connected };
}
