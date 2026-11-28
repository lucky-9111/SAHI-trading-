import { History } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ClipboardArt } from "../components/art";
import { MarketPill } from "../components/MarketStatus";
import { EmptyState, PageTitle, Sheet, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, istTime, parseTime } from "../utils/format";
import { useOrdersChanged } from "../utils/liveSocket";
import { displayName } from "../utils/names";

interface OrderRow {
  id: number; symbol: string; exchange: string; side: string; order_type: string; product: string; validity: string;
  quantity: number; filled_quantity: number; remaining_quantity: number;
  limit_price: string | null; trigger_price: string | null; avg_price: string | null; exec_price: string | null;
  status: string; reject_reason: string | null; after_market: boolean; reduce_only: boolean; cancellable: boolean;
  created_at: string; triggered_at: string | null; executed_at: string | null; updated_at: string | null; expires_at: string | null;
  strategy: string; chart_symbol: string; chart_exchange: string; stop_loss: string | null; target: string | null;
}
interface OrderDetail extends OrderRow {
  fills: { at: string; quantity: number; price: string; charges: string | null; event: string; reason: string }[];
  history: { at: string; kind: string; title: string; body: string }[];
}

/** Status label + colour. Every status shown here was set by the backend; the browser never decides an order's state. */
export const STATUS: Record<string, [string, string]> = {
  PENDING: ["Pending", "bg-[#fff1d6] text-[#8a5a00]"], OPEN: ["Open", "bg-[#e6f0ff] text-[#1f4fa8]"],
  TRIGGER_PENDING: ["Trigger pending", "bg-[#e6f0ff] text-[#1f4fa8]"], PARTIALLY_FILLED: ["Partially filled", "bg-[#e9f7f0] text-up"],
  FILLED: ["Executed", "bg-buybg text-buy"], REJECTED: ["Rejected", "bg-sellbg text-sell"],
  CANCELLED: ["Cancelled", "bg-soft text-muted"], EXPIRED: ["Expired", "bg-soft text-muted"],
};
const TABS = [
  ["all", "All", null], ["open", "Open", ["OPEN", "TRIGGER_PENDING", "PARTIALLY_FILLED"]], ["pending", "Pending", ["PENDING"]],
  ["executed", "Executed", ["FILLED"]], ["rejected", "Rejected", ["REJECTED"]], ["cancelled", "Cancelled", ["CANCELLED", "EXPIRED"]],
] as const;
type Tab = (typeof TABS)[number][0];
const TYPE: Record<string, string> = { MARKET: "Market", LIMIT: "Limit", SL: "SL", "SL-M": "SL-M" };

function when(iso: string) {
  const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const today = day(new Date()) === day(parseTime(iso));
  return today ? istTime(iso, { hour: "2-digit", minute: "2-digit" }) : istTime(iso, { day: "2-digit", month: "short" });
}
const full = (iso: string | null) => (iso ? istTime(iso, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");

export function StatusBadge({ status }: { status: string }) {
  const [label, cls] = STATUS[status] ?? [status, "bg-soft text-muted"];
  return <span className={`rounded-md px-2 py-0.5 text-[12px] lg:text-[12.5px] font-medium whitespace-nowrap ${cls}`}>{label}</span>;
}

function priceLine(o: OrderRow) {
  if (o.order_type === "LIMIT") return `limit ${inr(o.limit_price)}`;
  if (o.order_type === "SL") return `trigger ${inr(o.trigger_price)} · limit ${inr(o.limit_price)}`;
  if (o.order_type === "SL-M") return `trigger ${inr(o.trigger_price)}`;
  return "at market";
}

function Field({ k, v, cls = "" }: { k: string; v: React.ReactNode; cls?: string }) {
  return <div className="flex justify-between gap-3 py-1.5 text-[14px] lg:text-[15px]"><span className="text-muted">{k}</span><span className={`text-right ${cls}`}>{v}</span></div>;
}

function DetailSheet({ id, accountId, onClose, onCancel, busy }: { id: number; accountId: number; onClose: () => void; onCancel: (id: number) => void; busy: boolean }) {
  const [d, setD] = useState<OrderDetail | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    api<OrderDetail>(`/api/accounts/${accountId}/orders/${id}`).then(setD).catch((e) => setErr(e.message));
  }, [accountId, id]);
  useEffect(load, [load]);
  useOrdersChanged(load);
  const buy = d?.side === "BUY";
  return (
    <Sheet open onClose={onClose} label={`Order ${id}`}>
      <div className="px-6 pt-2 pb-6">
        {err && <div role="alert" className="text-down text-[14px]">{err}</div>}
        {!d ? <Skeleton rows={5} /> : (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[19px] lg:text-[22px] truncate">{displayName(d.symbol)}</div>
                <div className="text-[13px] lg:text-[14px] text-muted mt-0.5">Order #{d.id} · {d.exchange}{d.after_market ? " · after-market" : ""}{d.reduce_only ? " · exit" : ""}</div>
              </div>
              <StatusBadge status={d.status} />
            </div>
            {d.reject_reason && d.status !== "FILLED" && (
              <div className={`rounded-2xl px-4 py-3 text-[14px] ${d.status === "REJECTED" ? "bg-sellbg/60 text-sell" : "bg-soft text-muted"}`}>
                {d.status === "REJECTED" ? "Rejected: " : ""}{d.reject_reason}
              </div>
            )}
            <div>
              <div className="text-[13px] uppercase tracking-wide text-faint mb-1">Order</div>
              <Field k="Side" v={<span className={buy ? "text-buy" : "text-sell"}>{d.side}</span>} />
              <Field k="Type" v={`${TYPE[d.order_type] ?? d.order_type} · ${d.product.toLowerCase()} · ${d.validity}`} />
              <Field k="Quantity" v={d.quantity} />
              {d.limit_price && <Field k="Limit price" v={inr(d.limit_price)} />}
              {d.trigger_price && <Field k="Trigger price" v={inr(d.trigger_price)} />}
              {d.stop_loss && <Field k="Stop loss" v={inr(d.stop_loss)} />}
              {d.target && <Field k="Target" v={inr(d.target)} />}
              <Field k="Placed" v={full(d.created_at)} />
              {d.expires_at && <Field k="Valid till" v={full(d.expires_at)} />}
              <Field k="Strategy" v={d.strategy} />
            </div>
            <div>
              <div className="text-[13px] uppercase tracking-wide text-faint mb-1">Execution</div>
              <Field k="Filled / remaining" v={`${d.filled_quantity} / ${d.remaining_quantity}`} />
              <Field k="Average price" v={d.avg_price ? inr(d.avg_price) : "—"} />
              {d.triggered_at && <Field k="Triggered" v={full(d.triggered_at)} />}
              <Field k="Last execution" v={full(d.executed_at)} />
              {d.fills.length > 0 && (
                <div className="mt-2 rounded-2xl bg-soft px-4 py-2">
                  {d.fills.map((f, i) => (
                    <div key={i} className="flex justify-between text-[13.5px] py-1"><span className="text-muted">{full(f.at)}</span><span>{f.quantity} @ {inr(f.price)}</span></div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="text-[13px] uppercase tracking-wide text-faint mb-2">History</div>
              <ol className="border-l border-line ml-1.5 space-y-3">
                {d.history.map((h, i) => (
                  <li key={i} className="pl-4 relative">
                    <span className="absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full bg-ink" />
                    <div className="flex justify-between gap-2"><span className="text-[14px] font-medium">{h.title}</span><span className="text-[12px] text-faint whitespace-nowrap">{full(h.at)}</span></div>
                    {h.body && <div className="text-[13px] text-muted break-words">{h.body}</div>}
                  </li>
                ))}
              </ol>
            </div>
            <div className="flex gap-3">
              {d.cancellable && (
                <button className="btn flex-1 py-3.5 border border-sell text-sell text-[15.5px]" disabled={busy} onClick={() => onCancel(d.id)}>{busy ? "Cancelling…" : "Cancel order"}</button>
              )}
              <Link to={`/trade?symbol=${d.chart_symbol}&exchange=${d.chart_exchange}`} className="btn-ghost flex-1 py-3.5 text-[15.5px]">Chart</Link>
            </div>
          </div>
        )}
      </div>
    </Sheet>
  );
}

export default function OrderBookPage() {
  const { accountId, refreshAccounts } = useAuth();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const openId = Number(params.get("order")) || null;

  const load = useCallback(() => {
    if (!accountId) return;
    api<OrderRow[]>(`/api/accounts/${accountId}/orders`).then((r) => { setRows(r); setError(""); }).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);

  const cancel = async (id: number) => {
    setBusy(id);
    try { await api(`/api/accounts/${accountId}/orders/${id}/cancel`, { method: "POST" }); load(); refreshAccounts(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const show = (id: number | null) => setParams(id ? { order: String(id) } : {}, { replace: true });
  const statuses = TABS.find((t) => t[0] === tab)?.[2] as readonly string[] | null;
  const all = rows ?? [];
  const shown = all.filter((r) => !statuses || statuses.includes(r.status));
  const count = (st: readonly string[] | null) => (st ? all.filter((r) => st.includes(r.status)).length : all.length);

  return (
    <div className="lg:max-w-[880px]">
      <PageTitle right={<Link to="/trade-book" className="mb-1.5 inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-[13px] lg:text-[14px] press"><History size={16} />Trade history</Link>}>Orders</PageTitle>
      <div className="hidden lg:block -mt-2 mb-3"><MarketPill /></div>
      {error && <div role="alert" className="mx-4 lg:mx-0 mb-3 rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] lg:text-[15px] text-sell">{error}</div>}
      {rows === null ? <div className="px-4 lg:px-0"><Skeleton rows={6} /></div> : rows.length === 0 ? (
        <EmptyState art={<ClipboardArt />} title="You don’t have any orders" text="Place your first paper trade."
                    action={<button className="btn-pill" onClick={() => nav("/funds")}>Add money</button>} />
      ) : (
        <>
          <div className="px-4 lg:px-0 flex gap-2 overflow-x-auto no-scrollbar" role="tablist" aria-label="Order filter">
            {TABS.map(([k, label, st]) => {
              const n = count(st);
              return (
                <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "chip-on" : "chip"} onClick={() => setTab(k)}>
                  {label}{k !== "all" && n ? <span className="text-faint">{n}</span> : null}
                </button>
              );
            })}
          </div>
          <div className="px-4 lg:px-0 mt-2">
            {shown.length === 0 && <div className="py-12 text-center text-muted">No orders here.</div>}
            {shown.map((o) => {
              const buy = o.side === "BUY";
              return (
                <div key={o.id} className="row items-start">
                  <button onClick={() => show(o.id)} className="flex-1 min-w-0 text-left active:opacity-60">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`rounded-md px-2 py-0.5 text-[12px] lg:text-[13px] font-medium ${buy ? "bg-buybg text-buy" : "bg-sellbg text-sell"}`}>{o.side}</span>
                      <span className="row-name">{displayName(o.symbol)}</span>
                    </div>
                    <div className="row-sub">
                      {o.filled_quantity > 0 && o.filled_quantity < o.quantity ? `${o.filled_quantity}/${o.quantity}` : o.quantity} qty · {TYPE[o.order_type] ?? o.order_type} {priceLine(o) !== "at market" ? `· ${priceLine(o)}` : ""} · {o.product.toLowerCase()}{o.after_market ? " · AMO" : ""}{o.reduce_only ? " · exit" : ""}
                    </div>
                    {o.reject_reason && o.status !== "FILLED" && <div className={`text-[12px] lg:text-[13px] mt-1 ${o.status === "REJECTED" ? "text-down" : "text-muted"}`}>{o.reject_reason}</div>}
                  </button>
                  <div className="text-right shrink-0">
                    <div className="row-price">{o.avg_price ? inr(o.avg_price) : o.limit_price ? inr(o.limit_price) : o.trigger_price ? inr(o.trigger_price) : "Market"}</div>
                    <div className="row-chg flex items-center justify-end gap-1.5"><StatusBadge status={o.status} /><span className="text-muted">{when(o.created_at)}</span></div>
                    {o.cancellable && (
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
      {openId && accountId && <DetailSheet id={openId} accountId={accountId} onClose={() => show(null)} onCancel={cancel} busy={busy === openId} />}
    </div>
  );
}
