import { LineChart } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr } from "../utils/format";

interface OrderRow {
  id: number; symbol: string; side: string; order_type: string; product: string; quantity: number;
  limit_price: string | null; exec_price: string | null; status: string; reject_reason: string | null; created_at: string;
  strategy: string; chart_symbol: string; chart_exchange: string; validity: string;
}
const STATUS: Record<string, string> = {
  EXECUTED: "text-up", PENDING: "text-amber-600", CANCELLED: "text-muted", REJECTED: "text-down", EXECUTING: "text-amber-600",
};

export default function OrderBookPage() {
  const { accountId } = useAuth();
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  const [filter, setFilter] = useState("ALL");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!accountId) return;
    api<OrderRow[]>(`/api/accounts/${accountId}/orders`).then(setRows).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const cancel = async (id: number) => {
    try { await api(`/api/accounts/${accountId}/orders/${id}/cancel`, { method: "POST" }); load(); }
    catch (e) { setError((e as Error).message); }
  };
  const shown = (rows ?? []).filter((r) => filter === "ALL" || r.status === filter);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Orders</h1>
        <div className="flex gap-2 flex-wrap" role="tablist" aria-label="Status filter">
          {[["ALL", "All"], ["PENDING", "Open"], ["EXECUTED", "Executed"], ["CANCELLED", "Cancelled"], ["REJECTED", "Rejected"]].map(([v, l]) => (
            <button key={v} role="tab" className={filter === v ? "chip-on" : "chip"} onClick={() => setFilter(v)}>{l}</button>
          ))}
        </div>
      </div>
      {error && <div role="alert" className="text-down text-sm">{error}</div>}
      <div className="panel overflow-x-auto">
        <table className="w-full">
          <thead><tr className="border-b border-line">
            {["Order ID", "Time", "Symbol", "Strategy", "Type", "Side", "Qty", "Order price", "Exec price", "Status", ""].map((h) => <th key={h} className="th">{h}</th>)}
          </tr></thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.id} className="border-b border-line/50">
                <td className="td">#{o.id}</td>
                <td className="td">{new Date(o.created_at).toLocaleString("en-IN")}</td>
                <td className="td font-medium">{o.symbol}<div className="text-[11px] text-muted">{o.product}</div></td>
                <td className="td">{o.strategy}</td>
                <td className="td">{o.order_type}{o.order_type !== "MARKET" && <div className="text-[11px] text-muted">{o.validity}</div>}</td>
                <td className={`td ${o.side === "BUY" ? "text-up" : "text-down"}`}>{o.side}</td>
                <td className="td">{o.quantity}</td>
                <td className="td">{o.limit_price ? `${o.order_type === "TRIGGER" ? "Trigger " : ""}${inr(o.limit_price)}` : "Market"}</td>
                <td className="td">{o.exec_price ? inr(o.exec_price) : "—"}</td>
                <td className={`td ${STATUS[o.status] ?? ""}`}>{o.status}{o.reject_reason && <div className="text-[11px]">{o.reject_reason}</div>}</td>
                <td className="td whitespace-nowrap">
                  <Link className="btn-ghost !py-1" to={`/trade?symbol=${o.chart_symbol}&exchange=${o.chart_exchange}`}
                        title={`Open ${o.chart_symbol} chart`}><LineChart size={14} /> Chart</Link>
                  {o.status === "PENDING" && <button className="btn-ghost !py-1 ml-1" onClick={() => cancel(o.id)}>Cancel</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <div className="text-sm text-muted py-10 text-center">No orders.</div>}
      </div>
    </div>
  );
}
