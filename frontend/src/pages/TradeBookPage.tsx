import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChartArt } from "../components/art";
import { BackBar, EmptyState, PageTitle, Segmented, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, istTime, parseTime, pnlClass, price } from "../utils/format";
import { displayName } from "../utils/names";

interface TradeRow {
  id: number; symbol: string; side: string; quantity: number; entry_price: string; exit_price: string;
  gross_pnl: string; charges: string; net_pnl: string; exit_reason: string; strategy: string;
  entry_time: string; exit_time: string; chart_symbol: string; chart_exchange: string;
}

function duration(a: string, b: string): string {
  const mins = Math.max(0, Math.round((parseTime(b).getTime() - parseTime(a).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d`;
}

export default function TradeBookPage() {
  const { accountId } = useAuth();
  const [rows, setRows] = useState<TradeRow[] | null>(null);
  const [result, setResult] = useState<"ALL" | "PROFIT" | "LOSS">("ALL");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!accountId) return;
    api<TradeRow[]>(`/api/accounts/${accountId}/trades`).then(setRows).catch((e) => setError(e.message));
  }, [accountId]);

  const shown = (rows ?? []).filter((t) => result === "ALL" || (result === "PROFIT" ? Number(t.net_pnl) > 0 : Number(t.net_pnl) <= 0));
  const sum = (k: "gross_pnl" | "charges" | "net_pnl") => shown.reduce((a, t) => a + Number(t[k]), 0);
  const wins = shown.filter((t) => Number(t.net_pnl) > 0).length;
  return (
    <div className="lg:max-w-[820px]">
      <div className="lg:hidden"><BackBar /></div>
      <PageTitle>Trade history</PageTitle>
      {error && <div role="alert" className="mx-4 lg:mx-0 text-down text-[14px]">{error}</div>}
      {rows === null ? <div className="px-4 lg:px-0"><Skeleton rows={5} /></div> : rows.length === 0 ? (
        <EmptyState art={<ChartArt />} title="No completed trades yet" text="Closed trades and their net P&L appear here." />
      ) : (
        <>
          <div className="mx-4 lg:mx-0 card grid grid-cols-3 text-center px-3 py-4">
            <div><div className="text-[13px] text-muted">Net P&amp;L</div><div className={`text-[18px] font-medium ${pnlClass(sum("net_pnl"))}`}>{inr(sum("net_pnl"), true)}</div></div>
            <div><div className="text-[13px] text-muted">Charges</div><div className="text-[18px] font-medium">{inr(sum("charges"))}</div></div>
            <div><div className="text-[13px] text-muted">Win rate</div><div className="text-[18px] font-medium">{shown.length ? Math.round((wins / shown.length) * 100) : 0}%</div></div>
          </div>
          <div className="px-4 lg:px-0 mt-5"><Segmented value={result} onChange={setResult} items={[["ALL", "All"], ["PROFIT", "Profit"], ["LOSS", "Loss"]]} /></div>
          <div className="px-4 lg:px-0 mt-2">
            {shown.map((t) => (
              <Link key={t.id} to={`/trade?symbol=${t.chart_symbol}&exchange=${t.chart_exchange}`} className="row items-start active:bg-soft">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-md px-2 py-0.5 text-[12px] font-medium ${t.side === "BUY" ? "bg-buybg text-buy" : "bg-sellbg text-sell"}`}>{t.side === "BUY" ? "LONG" : "SHORT"}</span>
                    <span className="row-name">{displayName(t.symbol)}</span>
                  </div>
                  <div className="row-sub">{t.quantity} qty · {price(t.entry_price)} → {price(t.exit_price)} · {t.exit_reason.replace("_", " ").toLowerCase()} · {duration(t.entry_time, t.exit_time)}</div>
                  <div className="text-[13px] text-faint mt-0.5">{t.strategy} · {istTime(t.exit_time, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className={`row-price ${pnlClass(t.net_pnl)}`}>{inr(t.net_pnl, true)}</div>
                  <div className="row-chg text-muted">charges {inr(t.charges)}</div>
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
