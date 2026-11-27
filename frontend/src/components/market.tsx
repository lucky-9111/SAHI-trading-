import { Link } from "react-router-dom";
import { changeText, pnlClass, price } from "../utils/format";

export interface QuoteRow {
  symbol: string; exchange: string; instrument_id: number;
  ltp: string | null; prev_close: string | null; change: string | null; pct: string | null; volume: number | null;
}
export interface IndexRow {
  key: string; name: string; exchange: string; ltp: string; change: string; pct: string; trend: string;
}

export function IndexCard({ i, active, onClick }: { i: IndexRow; active?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick}
            className={`panel text-left px-4 py-3 min-w-[190px] hover:bg-soft ${active ? "!border-slate-900" : ""}`}>
      <div className="text-xs text-muted">{i.name}</div>
      <div className="mt-1 text-xl font-semibold">{price(i.ltp)}</div>
      <div className={`text-sm ${pnlClass(i.change)}`}>{changeText(i.change, i.pct)}</div>
    </button>
  );
}

const TREND_STYLE: Record<string, string> = {
  "Strong uptrend": "bg-[#cdeee2]", Uptrend: "bg-[#e3f5ee]",
  "Strong downtrend": "bg-[#f8c9c9]", Downtrend: "bg-[#fde6e6]", Sideways: "bg-panel2",
};

export function TrendTile({ i }: { i: IndexRow }) {
  return (
    <div className={`rounded-2xl p-4 min-h-[110px] flex flex-col justify-between ${TREND_STYLE[i.trend] ?? "bg-panel2"}`}>
      <div>
        <div className="font-medium">{i.name}</div>
        <div className={`text-sm ${pnlClass(i.pct)}`}>{Number(i.pct) > 0 ? "+" : ""}{Number(i.pct).toFixed(2)}%</div>
      </div>
      <div className="text-xs font-medium text-slate-700">{i.trend}</div>
    </div>
  );
}

export function StockRow({ r, action }: { r: QuoteRow; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-line last:border-0">
      <Link to={`/trade?symbol=${r.symbol}&exchange=${r.exchange}`} className="flex-1 min-w-0 hover:opacity-70">
        <div className="font-medium">{r.symbol}</div>
        <div className="text-xs text-muted">{r.exchange}</div>
      </Link>
      <div className="text-right">
        <div className="font-medium">{price(r.ltp)}</div>
        <div className={`text-xs ${r.change ? pnlClass(r.change) : "text-muted"}`}>{changeText(r.change, r.pct)}</div>
      </div>
      {action && <div className="ml-3">{action}</div>}
    </div>
  );
}
