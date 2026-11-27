import { Link } from "react-router-dom";
import { changeText, pnlClass, price } from "../utils/format";
import { COMMODITY_NAMES, displayName } from "../utils/names";
import { CommodityIcon } from "./art";
import { Flash, PriceCell } from "./ui";

export interface QuoteRow {
  symbol: string; exchange: string; instrument_id: number; token?: string; feed_exchange?: string;
  ltp: string | null; prev_close: string | null; change: string | null; pct: string | null; volume: number | null;
}
export interface IndexRow {
  key: string; name: string; exchange: string; token?: string; prev_close?: string | null; ltp: string; change: string; pct: string; trend: string;
}
export interface ContractQuote extends QuoteRow { contract: string; expiry: string | null; lot_size: number }

/** Same thresholds as the server's trend label, so a tile can follow the live % change. */
export function trendLabel(pct: number): string {
  if (pct >= 1.5) return "Strong uptrend";
  if (pct >= 0.25) return "Uptrend";
  if (pct <= -1.5) return "Strong downtrend";
  if (pct <= -0.25) return "Downtrend";
  return "Sideways";
}

/** Index key on the home screen -> the symbol the trade page opens (futures / options of that index). */
export const INDEX_TRADE: Record<string, string> = { NIFTY50: "NIFTY", BANKNIFTY: "BANKNIFTY", FINNIFTY: "FINNIFTY", MIDCPNIFTY: "MIDCPNIFTY" };

export function IndexCard({ i, active, onClick, to }: { i: IndexRow; active?: boolean; onClick?: () => void; to?: string }) {
  const body = (
    <>
      <div className="text-[13px] lg:text-[15.5px] text-ink truncate">{i.key}</div>
      <div className="mt-2 lg:mt-2.5 text-[16.5px] lg:text-[20px] font-medium leading-none whitespace-nowrap"><Flash value={i.ltp}>{price(i.ltp)}</Flash></div>
      <div className={`mt-1 lg:mt-1.5 text-[13px] lg:text-[15.5px] whitespace-nowrap ${pnlClass(i.change)}`}>{changeText(i.change, i.pct)}</div>
    </>
  );
  const cls = `card shrink-0 w-[137px] lg:w-[210px] px-4 py-3 lg:py-4 text-left press transition-colors ${active ? "!border-ink border-[1.5px]" : ""}`;
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  return <button onClick={onClick} className={cls}>{body}</button>;
}

export function TrendTile({ i }: { i: IndexRow }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[14px] lg:text-[15px]">{i.key}</div>
      <div className={`text-[13px] lg:text-[14px] ${pnlClass(i.pct)}`}>{Number(i.pct) > 0 ? "+" : ""}{Number(i.pct).toFixed(2)}% · {i.trend}</div>
    </div>
  );
}

export function StockRow({ r, action, sub }: { r: QuoteRow; action?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="row">
      <Link to={`/trade?symbol=${r.symbol}&exchange=${r.exchange}`} className="flex-1 min-w-0 active:opacity-60">
        <div className="row-name">{displayName(r.symbol)}</div>
        <div className="row-sub">{sub ?? r.exchange}</div>
      </Link>
      <PriceCell ltp={r.ltp} change={r.change} pct={r.pct} />
      {action && <div className="ml-1">{action}</div>}
    </div>
  );
}

const fmtExpiry = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

/** A commodity / F&O underlying with its nearest future: links to the trade page of the underlying. */
export function ContractRow({ r, icon }: { r: ContractQuote; icon?: boolean }) {
  const expToday = r.expiry === today();
  const commodity = r.symbol in COMMODITY_NAMES;
  return (
    <div className="row">
      <Link to={`/trade?symbol=${r.symbol}&exchange=${r.exchange}`} className="flex-1 min-w-0 flex items-center gap-4 active:opacity-60">
        {icon && <CommodityIcon name={r.symbol} />}
        <div className="min-w-0">
          <div className="row-name">{displayName(r.symbol)}</div>
          <div className="row-sub flex items-center gap-2">
            <span>{commodity ? "MCX" : r.contract}</span>
            {r.expiry && (expToday
              ? <span className="rounded-md bg-panel2 px-2 py-0.5 text-[12px] lg:text-[13px] text-[#555]">Expiry Today</span>
              : commodity && <span className="text-[12px] lg:text-[13px] text-faint">Exp {fmtExpiry(r.expiry)}</span>)}
          </div>
        </div>
      </Link>
      <PriceCell ltp={r.ltp} change={r.change} pct={r.pct} />
    </div>
  );
}
