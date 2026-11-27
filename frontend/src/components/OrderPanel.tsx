import { ChevronsUpDown, Info, Minus, Plus, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, pnlClass } from "../utils/format";

interface Preview {
  ltp: string | null; market_open: boolean | null; entry_price: string | null; suggested_quantity: number | null;
  quantity: number; max_risk_amount: string; balance: string; errors: string[]; warnings: string[];
  order_value?: string; required_funds?: string; entry_charges?: string; risk_per_share?: string; total_risk?: string;
  reward_per_share?: string; potential_reward?: string; risk_reward?: string; estimated_net_reward?: string;
}
interface OrderResult { id: number; status: string; exec_price: string | null; reject_reason: string | null; side: string; quantity: number }
interface Strategy { id: number; name: string }
type OrderType = "MARKET" | "LIMIT" | "TRIGGER";

const PRODUCTS: Record<string, [string, string][]> = {
  EQ: [["DELIVERY", "Delivery"], ["INTRADAY", "Intraday"], ["SWING", "Swing"]],
  FUT: [["INTRADAY", "Intraday"], ["NRML", "Carry-forward"]],
  OPT: [["INTRADAY", "Intraday"], ["NRML", "Carry-forward"]],
};

function Segmented<T extends string>({ items, value, onChange, label }: {
  items: [T, string][]; value: T; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-full bg-panel2 p-1">
      {items.map(([v, l]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
                className={`rounded-full px-3.5 py-1.5 text-sm transition-colors ${
                  value === v ? "bg-accent text-white font-medium" : "text-slate-500 hover:text-slate-900"}`}>{l}</button>
      ))}
    </div>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
            className={`relative h-7 w-12 shrink-0 rounded-full border transition-colors ${on ? "bg-accent border-accent" : "bg-white border-slate-400"}`}>
      <span className={`absolute top-0.5 h-5.5 w-5.5 rounded-full transition-all ${on ? "left-[22px] bg-white" : "left-0.5 bg-slate-600"}`}
            style={{ height: 22, width: 22 }} />
    </button>
  );
}

function Line({ label, value, cls = "" }: { label: string; value: ReactNode; cls?: string }) {
  return <div className="flex justify-between text-xs py-0.5"><span className="text-muted">{label}</span><span className={cls}>{value}</span></div>;
}

function LevelCard({ badge, badgeCls, title, hint, on, onToggle, children }: {
  badge: string; badgeCls: string; title: string; hint: string; on: boolean; onToggle: (v: boolean) => void; children: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-line px-4 py-3">
      <div className="flex items-center gap-3">
        <span className={`h-9 w-9 grid place-items-center rounded-xl text-sm font-semibold ${badgeCls}`}>{badge}</span>
        <span className="font-medium">{title}</span>
        <span title={hint} className="text-muted"><Info size={15} /></span>
        <div className="flex-1" />
        <Toggle on={on} onChange={onToggle} label={title} />
      </div>
      {on && <div className="mt-3">{children}</div>}
    </div>
  );
}

export default function OrderPanel({ symbol, exchange, lotSize = 1, itype = "EQ", pct, onDone }: {
  symbol: string; exchange: string; lotSize?: number; itype?: "EQ" | "FUT" | "OPT"; pct?: string | null; onDone?: () => void;
}) {
  const { accountId, refreshAccounts } = useAuth();
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [product, setProduct] = useState<string>(itype === "EQ" ? "DELIVERY" : "INTRADAY");
  const [validity, setValidity] = useState<"DAY" | "GTT">("DAY");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("");
  const [slOn, setSlOn] = useState(false);
  const [tpOn, setTpOn] = useState(false);
  const [sl, setSl] = useState("");
  const [target, setTarget] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [details, setDetails] = useState(false);
  const [pv, setPv] = useState<Preview | null>(null);
  const [pvError, setPvError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const key = useRef(crypto.randomUUID());
  const lots = lotSize > 1;
  const buy = side === "BUY";
  const priced = orderType !== "MARKET";

  // Strategy list + remembered choice (unchanged behaviour)
  useEffect(() => {
    api<Strategy[]>("/api/strategies").then((list) => {
      setStrategies(list);
      let last = "";
      try { last = localStorage.getItem("agt_strategy") ?? ""; } catch { /* storage unavailable */ }
      const pick = list.find((s) => String(s.id) === last) ?? list.find((s) => s.name === "Manual") ?? list[0];
      if (pick) setStrategyId(String(pick.id));
    }).catch(() => {});
  }, []);
  useEffect(() => {
    if (!strategyId) return;
    try { localStorage.setItem("agt_strategy", strategyId); } catch { /* ignore */ }
  }, [strategyId]);

  const intraday = product === "INTRADAY";
  useEffect(() => { if (intraday) setValidity("DAY"); }, [intraday]);
  // Limit orders start at the current price, like the reference app
  useEffect(() => {
    if (orderType === "LIMIT" && !price && pv?.ltp) setPrice(String(Number(pv.ltp)));
  }, [orderType, pv?.ltp, price]);

  const body = () => ({
    symbol, exchange, side, order_type: orderType, product, validity,
    quantity: Number(qty) > 0 ? Number(qty) * lotSize : undefined,
    limit_price: priced && price ? price : undefined,
    stop_loss: slOn && sl ? sl : undefined, target: tpOn && target ? target : undefined,
    strategy_id: strategyId ? Number(strategyId) : undefined,
  });

  // Live calculator: all numbers come from the backend
  useEffect(() => {
    if (!accountId) return;
    const t = setTimeout(() => {
      api<Preview>(`/api/accounts/${accountId}/orders/preview`, { method: "POST", json: body() })
        .then((p) => { setPv(p); setPvError(""); })
        .catch((e) => setPvError(e.message));
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, symbol, side, orderType, product, qty, price, slOn, sl, tpOn, target, lotSize]);

  const place = async () => {
    if (!accountId) return;
    setBusy(true); setResult(null);
    try {
      const r = await api<OrderResult>(`/api/accounts/${accountId}/orders`, {
        method: "POST", json: { ...body(), idempotency_key: key.current },
      });
      key.current = crypto.randomUUID();
      if (r.status === "EXECUTED") setResult({ ok: true, text: `${r.side} ${r.quantity} ${symbol} executed at ${inr(r.exec_price)}` });
      else if (r.status === "PENDING") setResult({ ok: true, text: `${orderType === "TRIGGER" ? "Trigger" : "Limit"} order #${r.id} is pending. It fills when the price reaches your ${orderType === "TRIGGER" ? "trigger" : "limit"}.` });
      else setResult({ ok: false, text: `Order rejected: ${r.reject_reason}` });
      await refreshAccounts();
      onDone?.();
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const step = (d: number) => setQty(String(Math.max(1, (Number(qty) || 0) + d)));
  const blocked = !!pv && pv.errors.length > 0;
  const canPlace = !!accountId && !busy && Number(qty) > 0 && !blocked && (!priced || Number(price) > 0);
  const cash = pv?.required_funds && pv.entry_charges ? Number(pv.required_funds) - Number(pv.entry_charges) : null;
  const priceLabel = orderType === "TRIGGER" ? "Trigger" : "Limit";

  return (
    <div className="panel overflow-hidden">
      <div className="p-5 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-lg font-semibold truncate">{symbol}</div>
            <div className="text-sm">
              <span className="font-medium">{pv?.ltp ? inr(pv.ltp) : <span className="text-muted">No price</span>}</span>{" "}
              {pct && <span className={pnlClass(pct)}>({Number(pct) > 0 ? "+" : ""}{Number(pct).toFixed(2)}%)</span>}{" "}
              <span className="text-muted text-xs">{exchange}</span>
            </div>
          </div>
          <button type="button" onClick={() => setSide(buy ? "SELL" : "BUY")} aria-label={`Switch to ${buy ? "sell" : "buy"}`}
                  className={`inline-flex items-center gap-1 rounded-full px-3.5 py-1.5 text-sm font-medium ${buy ? "bg-[#e3f5ee] text-up" : "bg-[#fde6e6] text-down"}`}>
            {buy ? "Buy" : "Sell"}<ChevronsUpDown size={14} />
          </button>
        </div>

        <div className="flex items-center justify-between gap-2">
          <Segmented label="Product" items={PRODUCTS[itype]} value={product} onChange={setProduct} />
          <button type="button" aria-label="Order details" aria-pressed={details} onClick={() => setDetails(!details)} title="Risk, reward and charges"
                  className={`h-10 w-10 shrink-0 grid place-items-center rounded-full border ${details ? "border-slate-900 bg-panel2" : "border-line"}`}>
            <SlidersHorizontal size={16} />
          </button>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-slate-600">{lots ? "Lots" : "Quantity"}</div>
            {lots && <div className="text-[11px] text-muted">1 lot = {lotSize} qty{Number(qty) > 0 ? ` · total ${Number(qty) * lotSize}` : ""}</div>}
          </div>
          <div className="flex items-center rounded-full bg-panel2 px-1.5 py-1">
            <button type="button" aria-label="Decrease quantity" className="h-9 w-9 grid place-items-center rounded-full hover:bg-white" onClick={() => step(-1)}><Minus size={16} /></button>
            <input aria-label="Quantity" className="w-14 bg-transparent text-center font-medium outline-none" type="number" min="1" step="1"
                   value={qty} onChange={(e) => setQty(e.target.value)} />
            <button type="button" aria-label="Increase quantity" className="h-9 w-9 grid place-items-center rounded-full hover:bg-white" onClick={() => step(1)}><Plus size={16} /></button>
          </div>
        </div>
        <button type="button" className="-mt-3 text-xs text-muted underline-offset-2 hover:underline disabled:no-underline disabled:opacity-60"
                disabled={!pv?.suggested_quantity} title={pv ? `Risk ${inr(pv.max_risk_amount)} per trade` : ""}
                onClick={() => pv?.suggested_quantity && setQty(String(pv.suggested_quantity / lotSize))}>
          {pv?.suggested_quantity ? `Auto quantity from risk: ${pv.suggested_quantity / lotSize}${lots ? " lot(s)" : ""}` : "Add a stop loss to size by risk"}
        </button>

        <div className="flex items-center justify-between gap-3">
          <div className="text-slate-600">Order type</div>
          <Segmented label="Order type" items={[["MARKET", "Market"], ["LIMIT", "Limit"], ["TRIGGER", "Trigger"]]} value={orderType}
                     onChange={(t) => { setOrderType(t); if (t === "TRIGGER") setPrice(""); }} />
        </div>

        {priced && (
          <div className="flex items-center justify-between gap-3">
            <div className="text-slate-600">{orderType === "TRIGGER" ? "Trigger price" : "Price"} <b className="text-slate-900">{orderType === "LIMIT" ? "Limit" : ""}</b></div>
            <input aria-label={`${priceLabel} price`} className="input !w-40 text-right text-base font-medium" type="number" step="0.05"
                   value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
        )}

        {!intraday && (
          <div className="flex items-center justify-between gap-3">
            <div className="text-slate-600">Validity</div>
            <Segmented label="Validity" items={[["DAY", "Day"], ["GTT", "GTT"]]} value={validity} onChange={setValidity} />
          </div>
        )}

        <LevelCard badge="SL" badgeCls="bg-[#fde6e6] text-down" title="Stop Loss" on={slOn}
                   hint="Closes the position automatically if the price moves against you to this level."
                   onToggle={(v) => { setSlOn(v); if (!v) setSl(""); }}>
          <input aria-label="Stop loss price" className="input" type="number" step="0.05" placeholder="Stop loss price ₹" value={sl} onChange={(e) => setSl(e.target.value)} />
        </LevelCard>
        <LevelCard badge="TP" badgeCls="bg-[#e3f5ee] text-up" title="Take Profit" on={tpOn}
                   hint="Closes the position automatically when the price reaches this target."
                   onToggle={(v) => { setTpOn(v); if (!v) setTarget(""); }}>
          <input aria-label="Target price" className="input" type="number" step="0.05" placeholder="Target price ₹" value={target} onChange={(e) => setTarget(e.target.value)} />
        </LevelCard>

        <label className="flex items-center justify-between gap-3 text-slate-600">Strategy
          <select className="input !w-auto min-w-[160px]" value={strategyId} onChange={(e) => setStrategyId(e.target.value)} aria-label="Strategy">
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>

        {details && (
          <div className="rounded-2xl bg-soft border border-line p-3">
            {pv?.order_value && <Line label="Order value" value={inr(pv.order_value)} />}
            {pv?.risk_per_share && <Line label="Risk per share" value={inr(pv.risk_per_share)} cls="text-down" />}
            {pv?.total_risk && <Line label="Total risk" value={inr(pv.total_risk)} cls="text-down" />}
            {pv?.reward_per_share && <Line label="Reward per share" value={inr(pv.reward_per_share)} cls="text-up" />}
            {pv?.potential_reward && <Line label="Potential reward" value={inr(pv.potential_reward)} cls="text-up" />}
            {pv?.risk_reward && <Line label="Risk : Reward" value={`1 : ${pv.risk_reward}`} />}
            {pv?.estimated_net_reward && <Line label="Est. net reward" value={inr(pv.estimated_net_reward, true)} />}
            {pv && <Line label="Max risk per trade" value={inr(pv.max_risk_amount)} />}
            {!pv?.risk_per_share && <div className="text-xs text-muted pt-1">Turn on Stop Loss and Take Profit to see risk and reward.</div>}
          </div>
        )}

        {pv?.warnings.filter((w) => !w.startsWith("Market is closed")).map((w) => <div key={w} className="text-xs text-amber-600">{w}</div>)}
        {pv?.errors.map((w) => <div key={w} role="alert" className="text-xs text-down">{w}</div>)}
        {pvError && <div role="alert" className="text-xs text-down">{pvError}</div>}
        {result && <div role="status" className={`text-sm ${result.ok ? "text-up" : "text-down"}`}>{result.text}</div>}
      </div>

      {pv?.market_open === false && (
        <div className="bg-soft border-t border-line px-5 py-3 text-sm text-slate-600">
          Market is closed. Market orders fill at the last traded price. Limit and trigger orders activate when the market opens.
        </div>
      )}
      <div className="border-t border-line px-5 py-4 flex items-center justify-between gap-3">
        <div className="text-xs leading-5 text-slate-600">
          <div>Est. balance: <span className="font-medium text-slate-900">{pv ? inr(pv.balance) : "₹0.00"}</span></div>
          {itype === "EQ"
            ? <div>Amount: <span className="font-medium text-slate-900">{pv?.order_value ? inr(pv.order_value) : "₹0.00"}</span></div>
            : <div title="Approximate fixed-percentage margin, not exchange SPAN">Req margin: <span className="font-medium text-slate-900">{cash !== null ? inr(cash) : "₹0.00"}</span></div>}
          <div title="Estimate for the entry leg">Charges: <span className="font-medium text-slate-900 underline decoration-dotted">{pv?.entry_charges ? inr(pv.entry_charges) : "₹0.00"}</span></div>
        </div>
        <button className={`btn px-10 py-3 text-base text-white ${buy ? "bg-[#0f7a4f] hover:bg-[#0c6642]" : "bg-[#c4372f] hover:bg-[#a82e27]"}`}
                disabled={!canPlace} onClick={place}>
          {busy ? "Placing…" : buy ? "Buy" : "Sell"}
        </button>
      </div>
      <div className="px-5 pb-3 text-[11px] text-muted">Paper trading: virtual money only. Charges are estimates.</div>
    </div>
  );
}
