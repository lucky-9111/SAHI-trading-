import { useMarketStatus, sessionHint, type MarketSession } from "../utils/marketStatus";
import { NotificationBell } from "./Notifications";

const DOT: Record<MarketSession["state"], string> = {
  OPEN: "bg-up animate-pulse", PRE_OPEN: "bg-amber-400", POST_CLOSE: "bg-amber-400", CLOSED: "bg-faint", WEEKEND: "bg-faint", HOLIDAY: "bg-sell",
};

/** "● Market open · Closes 15:30" (backend market status engine). */
export function MarketPill({ exchange = "NSE", hint = true }: { exchange?: string; hint?: boolean }) {
  const m = useMarketStatus(exchange);
  if (!m) return null;
  const h = hint ? sessionHint(m) : "";
  return (
    <span className="inline-flex items-center gap-2 text-[12px] lg:text-[13px] text-muted whitespace-nowrap" title={`${m.exchange}: ${m.label}`}>
      <span className={`h-2 w-2 rounded-full ${DOT[m.state]}`} />
      <span className="text-ink">{m.label.toUpperCase()}</span>{h && <span>· {h}</span>}
    </span>
  );
}

/** Thin bar at the top of phone screens: market status + order activity bell. */
export function MarketBar() {
  return (
    <div className="lg:hidden flex items-center justify-between gap-3 px-4 pt-2">
      <MarketPill />
      <NotificationBell className="h-9 w-9 grid place-items-center rounded-full text-ink active:bg-soft" />
    </div>
  );
}
