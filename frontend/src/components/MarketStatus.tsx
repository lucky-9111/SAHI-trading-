import { Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { istTime } from "../utils/format";
import { useMarketStatus, sessionHint, type MarketSession } from "../utils/marketStatus";
import { NotificationBell } from "./Notifications";
import { Sheet } from "./ui";

const HOURS: Record<string, string> = { NSE: "09:15 – 15:30", BSE: "09:15 – 15:30", NFO: "09:15 – 15:30", BFO: "09:15 – 15:30", MCX: "09:00 – 23:30" };

/** Shown instead of placing an order while the exchange is closed: nothing is bought and no money moves. */
export function MarketClosedDialog({ market, message, onClose }: { market: MarketSession | null | undefined; message: string; onClose: () => void }) {
  const ex = market?.exchange ?? "NSE";
  return (
    <Sheet open onClose={onClose} label="Market is closed">
      <div className="px-6 pt-4 pb-6 text-center">
        <div className="mx-auto h-14 w-14 rounded-full bg-sellbg grid place-items-center"><Clock size={28} className="text-sell" /></div>
        <div className="mt-4 text-[21px] lg:text-[23px] font-medium">Market is closed</div>
        <div className="mt-2 text-[14.5px] lg:text-[15px] text-muted">{message}</div>
        <div className="mt-5 rounded-2xl bg-soft px-4 py-3 text-left text-[14px] lg:text-[15px] space-y-1.5">
          <div className="flex justify-between gap-3"><span className="text-muted">Status</span><span>{market?.label ?? "Market closed"}</span></div>
          <div className="flex justify-between gap-3"><span className="text-muted">{ex} market hours</span><span>{HOURS[ex] ?? HOURS.NSE} IST, Mon–Fri</span></div>
          {market?.next_open && (
            <div className="flex justify-between gap-3"><span className="text-muted">Next session</span>
              <span>{istTime(market.next_open, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} IST</span></div>
          )}
        </div>
        <div className="mt-3 text-[13px] text-muted">Your order was not placed and no money was deducted.</div>
        <button className="btn-pill w-full mt-5" onClick={onClose}>OK</button>
        <Link to="/settings" onClick={onClose} className="block mt-3 text-[13px] text-muted underline underline-offset-2">
          Want orders queued for the next open? Turn on after-market orders (AMO) in Settings
        </Link>
      </div>
    </Sheet>
  );
}

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
