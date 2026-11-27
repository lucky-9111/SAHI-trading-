import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, istTime, pnlClass, price } from "../utils/format";

export interface CtxPosition {
  id: number; symbol: string; side: string; product: string; quantity: number; avg_price: string;
  stop_loss: string | null; target: string | null; unrealized_pnl: string | null; strategy: string;
  instrument_type: string; lot_size: number; opened_at: string;
}
export interface CtxOrder { id: number; symbol: string; side: string; order_type: string; quantity: number; limit_price: string | null; strategy: string }
export interface CtxTrade { id: number; symbol: string; side: string; quantity: number; entry_price: string; exit_price: string; net_pnl: string; strategy: string; exit_time: string; exit_reason: string }
export interface SymbolContext { positions: CtxPosition[]; orders: CtxOrder[]; trades: CtxTrade[] }

export function useSymbolContext(symbol: string, exchange: string, refreshKey: number): SymbolContext | null {
  const { accountId } = useAuth();
  const [ctx, setCtx] = useState<SymbolContext | null>(null);
  useEffect(() => {
    if (!accountId) return;
    let stop = false;
    const load = () => api<SymbolContext>(`/api/accounts/${accountId}/symbol-context?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}`)
      .then((c) => !stop && setCtx(c)).catch(() => {});
    setCtx(null); load();
    const t = setInterval(load, 10000);
    return () => { stop = true; clearInterval(t); };
  }, [accountId, symbol, exchange, refreshKey]);
  return ctx;
}

function Badge({ name }: { name: string }) {
  return <span className="inline-block rounded-full bg-slate-900 text-white text-xs font-medium px-2.5 py-0.5">{name}</span>;
}

/** Shows which strategy was chosen when the user entered trades in this symbol. */
export default function StrategyContext({ ctx }: { ctx: SymbolContext | null }) {
  if (!ctx || (ctx.positions.length === 0 && ctx.orders.length === 0 && ctx.trades.length === 0)) return null;
  const qty = (p: { quantity: number; lot_size?: number; instrument_type?: string }) =>
    p.instrument_type && p.instrument_type !== "EQ" && p.lot_size ? `${p.quantity / p.lot_size} lot(s)` : `${p.quantity}`;
  return (
    <div className="panel p-4 space-y-3">
      <h2 className="font-semibold">Your trades in this stock</h2>
      {ctx.positions.map((p) => (
        <div key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <Badge name={p.strategy} />
          <span className="text-muted">Open</span>
          <span className={p.side === "BUY" ? "text-up font-medium" : "text-down font-medium"}>{p.side === "BUY" ? "LONG" : "SHORT"}</span>
          <span>{p.symbol} · {qty(p)} @ {inr(p.avg_price)}</span>
          {p.stop_loss && <span className="text-muted">SL {price(p.stop_loss)}</span>}
          {p.target && <span className="text-muted">Target {price(p.target)}</span>}
          {p.unrealized_pnl && <span className={`font-medium ${pnlClass(p.unrealized_pnl)}`}>{inr(p.unrealized_pnl, true)}</span>}
        </div>
      ))}
      {ctx.orders.map((o) => (
        <div key={o.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <Badge name={o.strategy} />
          <span className="text-amber-600">Pending {o.order_type.toLowerCase()}</span>
          <span>{o.side} {o.symbol} · {o.quantity}{o.limit_price ? ` @ ${inr(o.limit_price)}` : ""}</span>
        </div>
      ))}
      {ctx.trades.length > 0 && (
        <div className="border-t border-line pt-2 space-y-1.5">
          <div className="text-xs text-muted">Recent closed trades</div>
          {ctx.trades.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <Badge name={t.strategy} />
              <span>{t.side === "BUY" ? "Long" : "Short"} {t.quantity} · {price(t.entry_price)} → {price(t.exit_price)}</span>
              <span className={`font-medium ${pnlClass(t.net_pnl)}`}>{inr(t.net_pnl, true)}</span>
              <span className="text-xs text-muted">{t.exit_reason.replace("_", " ").toLowerCase()} · {istTime(t.exit_time, { day: "2-digit", month: "short" })}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
