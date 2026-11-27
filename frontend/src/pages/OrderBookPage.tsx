import { History } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ClipboardArt } from "../components/art";
import { EmptyState, PageTitle, Segmented, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, istTime, parseTime } from "../utils/format";
import { useOrdersChanged } from "../utils/liveSocket";
import { displayName } from "../utils/names";

interface OrderRow {
  id: number; symbol: string; side: string; order_type: string; product: string; quantity: number;
  limit_price: string | null; exec_price: string | null; status: string; reject_reason: string | null; created_at: string;
  strategy: string; chart_symbol: string; chart_exchange: string; validity: string; exchange: string;
}
const STATUS: Record<string, [string, string]> = {
  EXECUTED: ["Executed", "text-up"], PENDING: ["Open", "text-[#b26a00]"], EXECUTING: ["Executing", "text-[#b26a00]"],
  CANCELLED: ["Cancelled", "text-muted"], REJECTED: ["Rejected", "text-down"],
};
type F = "open" | "done" | "all";

function when(iso: string) {
  const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const today = day(new Date()) === day(parseTime(iso));
  return today ? istTime(iso, { hour: "2-digit", minute: "2-digit" }) : istTime(iso, { day: "2-digit", month: "short" });
}

export default function OrderBookPage() {
  const { accountId } = useAuth();
  const nav = useNavigate();
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  const [filter, setFilter] = useState<F>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!accountId) return;
    api<OrderRow[]>(`/api/accounts/${accountId}/orders`).then((r) => { setRows(r); setError(""); }).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);

  const cancel = async (id: number) => {
    setBusy(id);
    try { await api(`/api/accounts/${accountId}/orders/${id}/cancel`, { method: "POST" }); load(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const shown = (rows ?? []).filter((r) => filter === "all" || (filter === "open" ? r.status === "PENDING" : r.status !== "PENDING"));
  const openCount = (rows ?? []).filter((r) => r.status === "PENDING").length;

  return (
    <div className="lg:max-w-[820px]">
      <PageTitle right={<Link to="/trade-book" className="mb-1.5 inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-[13px] lg:text-[14px] press"><History size={16} />Trade history</Link>}>Orders</PageTitle>
      {error && <div role="alert" className="mx-4 lg:mx-0 mb-3 rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] lg:text-[15px] text-sell">{error}</div>}
      {rows === null ? <div className="px-4 lg:px-0"><Skeleton rows={6} /></div> : rows.length === 0 ? (
        <EmptyState art={<ClipboardArt />} title="You don’t have any orders" text="Place your first paper trade."
                    action={<button className="btn-pill" onClick={() => nav("/funds")}>Add money</button>} />
      ) : (
        <>
          <div className="px-4 lg:px-0">
            <Segmented value={filter} onChange={setFilter} items={[["all", "All"], ["open", `Open${openCount ? ` · ${openCount}` : ""}`], ["done", "Completed"]]} />
          </div>
          <div className="px-4 lg:px-0 mt-2">
            {shown.length === 0 && <div className="py-12 text-center text-muted">No orders here.</div>}
            {shown.map((o) => {
              const [label, cls] = STATUS[o.status] ?? [o.status, ""];
              const buy = o.side === "BUY";
              return (
                <div key={o.id} className="row items-start">
                  <Link to={`/trade?symbol=${o.chart_symbol}&exchange=${o.chart_exchange}`} className="flex-1 min-w-0 active:opacity-60">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-md px-2 py-0.5 text-[12px] lg:text-[13px] font-medium ${buy ? "bg-buybg text-buy" : "bg-sellbg text-sell"}`}>{buy ? "BUY" : "SELL"}</span>
                      <span className="row-name">{displayName(o.symbol)}</span>
                    </div>
                    <div className="row-sub">{o.quantity} qty · {o.product.toLowerCase()} · {o.order_type.toLowerCase()}{o.order_type !== "MARKET" ? ` ${inr(o.limit_price)}` : ""} · {o.strategy}</div>
                    {o.reject_reason && <div className="text-[12px] lg:text-[13px] text-down mt-1">{o.reject_reason}</div>}
                  </Link>
                  <div className="text-right shrink-0">
                    <div className="row-price">{o.exec_price ? inr(o.exec_price) : o.limit_price ? inr(o.limit_price) : "Market"}</div>
                    <div className={`row-chg ${cls}`}>{label} · {when(o.created_at)}</div>
                    {o.status === "PENDING" && (
                      <button className="mt-2 rounded-full border border-line px-3.5 py-1 text-[12px] lg:text-[13px] press disabled:opacity-40" disabled={busy === o.id} onClick={() => cancel(o.id)}>
                        {busy === o.id ? "Cancelling…" : "Cancel"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
