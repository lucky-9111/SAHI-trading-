import { LineChart } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, pnlClass } from "../utils/format";

interface TradeRow {
  id: number; symbol: string; side: string; quantity: number; entry_price: string; exit_price: string;
  gross_pnl: string; charges: string; net_pnl: string; exit_reason: string; strategy: string;
  entry_time: string; exit_time: string; chart_symbol: string; chart_exchange: string;
}

function duration(a: string, b: string): string {
  const mins = Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d`;
}

export default function TradeBookPage() {
  const { accountId } = useAuth();
  const [rows, setRows] = useState<TradeRow[] | null>(null);
  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState("ALL");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!accountId) return;
    api<TradeRow[]>(`/api/accounts/${accountId}/trades`).then(setRows).catch((e) => setError(e.message));
  }, [accountId]);

  const shown = (rows ?? []).filter((t) =>
    (!symbol || t.symbol.includes(symbol.toUpperCase())) &&
    (result === "ALL" || (result === "PROFIT" ? Number(t.net_pnl) > 0 : Number(t.net_pnl) <= 0)));
  const sum = (k: "gross_pnl" | "charges" | "net_pnl") => shown.reduce((a, t) => a + Number(t[k]), 0);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <h1 className="text-lg font-semibold">Trade History</h1>
        <div className="flex gap-2">
          <input className="input !w-40" placeholder="Filter stock" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <select className="input !w-auto" value={result} onChange={(e) => setResult(e.target.value)} aria-label="Result filter">
            <option value="ALL">All</option><option value="PROFIT">Profit</option><option value="LOSS">Loss</option>
          </select>
        </div>
      </div>
      {error && <div role="alert" className="text-down text-sm">{error}</div>}
      <div className="panel overflow-x-auto">
        <table className="w-full">
          <thead><tr className="border-b border-line">
            {["Trade ID", "Exit time", "Stock", "Side", "Qty", "Entry", "Exit", "Gross P&L", "Charges", "Net P&L", "Strategy", "Held", "Exit reason", ""].map((h, i) => <th key={i} className="th">{h}</th>)}
          </tr></thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t.id} className="border-b border-line/50">
                <td className="td">#{t.id}</td>
                <td className="td">{new Date(t.exit_time).toLocaleString("en-IN")}</td>
                <td className="td font-medium">{t.symbol}</td>
                <td className={`td ${t.side === "BUY" ? "text-up" : "text-down"}`}>{t.side === "BUY" ? "LONG" : "SHORT"}</td>
                <td className="td">{t.quantity}</td>
                <td className="td">{inr(t.entry_price)}</td>
                <td className="td">{inr(t.exit_price)}</td>
                <td className={`td ${pnlClass(t.gross_pnl)}`}>{inr(t.gross_pnl, true)}</td>
                <td className="td text-muted">{inr(t.charges)}</td>
                <td className={`td font-medium ${pnlClass(t.net_pnl)}`}>{inr(t.net_pnl, true)}</td>
                <td className="td">{t.strategy}</td>
                <td className="td">{duration(t.entry_time, t.exit_time)}</td>
                <td className="td">{t.exit_reason.replace("_", " ")}</td>
                <td className="td">
                  <Link className="btn-ghost !py-1" to={`/trade?symbol=${t.chart_symbol}&exchange=${t.chart_exchange}`}
                        title={`Open ${t.chart_symbol} chart`}><LineChart size={14} /> Chart</Link>
                </td>
              </tr>
            ))}
          </tbody>
          {shown.length > 0 && (
            <tfoot><tr className="border-t border-line font-medium">
              <td className="td" colSpan={7}>Total ({shown.length} trades)</td>
              <td className={`td ${pnlClass(sum("gross_pnl"))}`}>{inr(sum("gross_pnl"), true)}</td>
              <td className="td">{inr(sum("charges"))}</td>
              <td className={`td ${pnlClass(sum("net_pnl"))}`}>{inr(sum("net_pnl"), true)}</td>
              <td colSpan={4} />
            </tr></tfoot>
          )}
        </table>
        {shown.length === 0 && <div className="text-sm text-muted py-10 text-center">No completed trades yet.</div>}
      </div>
    </div>
  );
}
