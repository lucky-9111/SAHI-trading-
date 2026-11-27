import { ChevronsUpDown, Info, Minus, Plus, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, pnlClass } from "../utils/format";
import { useLiveTick } from "../utils/liveSocket";
import { displayName } from "../utils/names";
import { uuid } from "../utils/uuid";
import { Segmented, Switch } from "./ui";

interface Preview {
  ltp: string | null; market_open: boolean | null; entry_price: string | null; suggested_quantity: number | null;
  quantity: number; max_risk_amount: string; balance: string; errors: string[]; warnings: string[];
  order_value?: string; required_funds?: string; entry_charges?: string; risk_per_share?: string; total_risk?: string;
  reward_per_share?: string; potential_reward?: string; risk_reward?: string; estimated_net_reward?: string;
}
interface OrderResult { id: number; status: string; exec_price: string | null; reject_reason: string | null; side: string; quantity: number }
interface Strategy { id: number; name: string }
type OrderType = "MARKET" | "LIMIT" | "TRIGGER";
type Side = "BUY" | "SELL";

const PRODUCTS: Record<string, [string, string][]> = {
  EQ: [["DELIVERY", "Delivery"], ["INTRADAY", "Intraday"], ["SWING", "Swing"]],
  FUT: [["INTRADAY", "Intraday"], ["NRML", "Carry forward"]],
  OPT: [["INTRADAY", "Intraday"], ["NRML", "Carry forward"]],
};

function Line({ label, value, cls = "" }: { label: string; value: ReactNode; cls?: string }) {
  return <div className="flex justify-between text-[14px] py-1"><span className="text-muted">{label}</span><span className={cls}>{value}</span></div>;
}

function LevelCard({ badge, badgeCls, title, hint, on, onToggle, children }: {
  badge: string; badgeCls: string; title: string; hint: string; on: boolean; onToggle: (v: boolean) => void; children: ReactNode;
}) {
  return (
    <div className="rounded-[20px] border border-line px-4 py-3.5 transition-all">
      <div className="flex items-center gap-4">
        <span className={`h-10 w-10 grid place-items-center rounded-xl text-[16px] font-medium ${badgeCls}`}>{badge}</span>
        <span className="text-[17px]">{title}</span>
        <span title={hint} className="text-ink"><Info size={19} strokeWidth={1.7} /></span>
        <div className="flex-1" />
        <Switch on={on} onChange={onToggle} label={title} />
      </div>
      {on && <div className="mt-4 animate-fade">{children}</div>}
    </div>
  );
}

export default function OrderPanel({ symbol, exchange, lotSize = 1, itype = "EQ", pct, onDone, initialSide = "BUY", sheet = false, token }: {
  symbol: string; exchange: string; lotSize?: number; itype?: "EQ" | "FUT" | "OPT"; pct?: string | null; onDone?: () => void;
  initialSide?: Side; sheet?: boolean; token?: string;
}) {
  const { accountId, refreshAccounts } = useAuth();
  const [side, setSide] = useState<Side>(initialSide);
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
  const key = useRef(uuid());
  const lots = lotSize > 1;
  const buy = side === "BUY";
  const priced = orderType !== "MARKET";
  const { tick, fresh } = useLiveTick(token ? exchange : undefined, token);
  const ltp = fresh && tick ? String(tick.ltp) : pv?.ltp ?? null;

  useEffect(() => { setSide(initialSide); }, [initialSide]);
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
  useEffect(() => {
    if (orderType === "LIMIT" && !price && ltp) setPrice(String(Number(ltp)));
  }, [orderType, ltp, price]);

  const body = () => ({
    symbol, exchange, side, order_type: orderType, product, validity,
    quantity: Number(qty) > 0 ? Number(qty) * lotSize : undefined,
    limit_price: priced && price ? price : undefined,
    stop_loss: slOn && sl ? sl : undefined, target: tpOn && target ? target : undefined,
    strategy_id: strategyId ? Number(strategyId) : undefined,
  });

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
      const r = await api<OrderResult>(`/api/accounts/${accountId}/orders`, { method: "POST", json: { ...body(), idempotency_key: key.current } });
      key.current = uuid();
      if (r.status === "EXECUTED") setResult({ ok: true, text: `${r.side} ${r.quantity} ${symbol} executed at ${inr(r.exec_price)}` });
      else if (r.status === "PENDING") setResult({ ok: true, text: `${orderType === "TRIGGER" ? "Trigger" : "Limit"} order #${r.id} is open. It fills when the price reaches your ${orderType === "TRIGGER" ? "trigger" : "limit"}.` });
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
  const label = "text-[17px] text-[#555]";

  return (
    <div className={sheet ? "" : "card overflow-hidden"}>
      <div className="px-5 pt-4 pb-6 space-y-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[22px] truncate">{displayName(symbol)}</div>
            <div className="text-[18px] mt-0.5 flex items-baseline gap-2">
              <span className="font-medium">{ltp ? Number(ltp).toFixed(2) : <span className="text-muted text-[15px]">No price</span>}</span>
              {pct && <span className={pnlClass(pct)}>({Number(pct) > 0 ? "+" : ""}{Number(pct).toFixed(2)}%)</span>}
              <span className="text-muted text-[16px]">{exchange}</span>
            </div>
          </div>
          <button type="button" onClick={() => setSide(buy ? "SELL" : "BUY")} aria-label={`Switch to ${buy ? "sell" : "buy"}`}
                  className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[17px] press transition-colors ${buy ? "bg-buybg text-buy" : "bg-sellbg text-sell"}`}>
            {buy ? "Buy" : "Sell"}<ChevronsUpDown size={17} />
          </button>
        </div>

        <div className="flex items-center justify-between gap-2">
          <Segmented label="Product" items={PRODUCTS[itype] as [string, string][]} value={product} onChange={setProduct} />
          <button type="button" aria-label="Order details" aria-pressed={details} onClick={() => setDetails(!details)} title="Risk, reward and charges"
                  className={`h-12 w-12 shrink-0 grid place-items-center rounded-full border transition-colors ${details ? "border-ink bg-soft" : "border-line"}`}>
            <SlidersHorizontal size={19} strokeWidth={1.7} />
          </button>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <div className={label}>{lots ? "Lots" : "Quantity"}</div>
            {lots && <div className="text-[13px] text-muted">1 lot = {lotSize} qty{Number(qty) > 0 ? ` · total ${Number(qty) * lotSize}` : ""}</div>}
          </div>
          <div className="flex items-center rounded-full bg-panel2 px-1.5 py-1.5">
            <button type="button" aria-label="Decrease quantity" className="h-11 w-11 grid place-items-center rounded-full active:bg-white text-[#555]" onClick={() => step(-1)}><Minus size={22} strokeWidth={1.6} /></button>
            <input aria-label="Quantity" className="w-16 bg-transparent text-center text-[19px] outline-none" type="number" min="1" step="1" inputMode="numeric"
                   value={qty} onChange={(e) => setQty(e.target.value)} />
            <button type="button" aria-label="Increase quantity" className="h-11 w-11 grid place-items-center rounded-full active:bg-white text-[#555]" onClick={() => step(1)}><Plus size={22} strokeWidth={1.6} /></button>
          </div>
        </div>
        {pv?.suggested_quantity ? (
          <button type="button" className="-mt-5 text-[13px] text-muted underline underline-offset-2" title={`Risk ${inr(pv.max_risk_amount)} per trade`}
                  onClick={() => setQty(String(pv.suggested_quantity! / lotSize))}>
            Size by risk: {pv.suggested_quantity / lotSize}{lots ? " lot(s)" : ""}
          </button>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <div className={label}>Order type</div>
          <Segmented tone="light" label="Order type" items={[["MARKET", "Market"], ["LIMIT", "Limit"], ["TRIGGER", "Trigger"]]} value={orderType}
                     onChange={(t) => { setOrderType(t); if (t === "TRIGGER") setPrice(""); }} />
        </div>

        {priced && (
          <div className="flex items-center justify-between gap-3 animate-fade">
            <div className={label}>Price <b className="font-medium text-ink">{orderType === "TRIGGER" ? "Trigger" : "Limit"}</b></div>
            <input aria-label={`${orderType === "TRIGGER" ? "Trigger" : "Limit"} price`} className="input !w-[190px] !rounded-2xl text-right text-[20px]" type="number" step="0.05" inputMode="decimal"
                   value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
        )}

        {!intraday && (
          <div className="flex items-center justify-between gap-3">
            <div className={label}>Validity</div>
            <Segmented tone="light" label="Validity" items={[["DAY", "Day"], ["GTT", "GTT"]]} value={validity} onChange={setValidity} />
          </div>
        )}

        <LevelCard badge="SL" badgeCls="bg-sellbg text-sell" title="Stop Loss" on={slOn}
                   hint="Closes the position automatically if the price moves against you to this level."
                   onToggle={(v) => { setSlOn(v); if (!v) setSl(""); }}>
          <input aria-label="Stop loss price" className="input text-right text-[18px]" type="number" step="0.05" inputMode="decimal" placeholder="Stop loss price ₹" value={sl} onChange={(e) => setSl(e.target.value)} />
        </LevelCard>
        <LevelCard badge="TP" badgeCls="bg-buybg text-buy" title="Take Profit" on={tpOn}
                   hint="Closes the position automatically when the price reaches this target."
                   onToggle={(v) => { setTpOn(v); if (!v) setTarget(""); }}>
          <input aria-label="Target price" className="input text-right text-[18px]" type="number" step="0.05" inputMode="decimal" placeholder="Target price ₹" value={target} onChange={(e) => setTarget(e.target.value)} />
        </LevelCard>

        <label className="flex items-center justify-between gap-3"><span className={label}>Strategy</span>
          <select className="h-12 rounded-full border border-line bg-white px-4 text-[16px] min-w-[170px]" value={strategyId} onChange={(e) => setStrategyId(e.target.value)} aria-label="Strategy">
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>

        {details && (
          <div className="rounded-[20px] bg-soft p-4 animate-fade">
            {pv?.order_value && <Line label="Order value" value={inr(pv.order_value)} />}
            {pv?.risk_per_share && <Line label="Risk per share" value={inr(pv.risk_per_share)} cls="text-down" />}
            {pv?.total_risk && <Line label="Total risk" value={inr(pv.total_risk)} cls="text-down" />}
            {pv?.reward_per_share && <Line label="Reward per share" value={inr(pv.reward_per_share)} cls="text-up" />}
            {pv?.potential_reward && <Line label="Potential reward" value={inr(pv.potential_reward)} cls="text-up" />}
            {pv?.risk_reward && <Line label="Risk : Reward" value={`1 : ${pv.risk_reward}`} />}
            {pv?.estimated_net_reward && <Line label="Est. net reward" value={inr(pv.estimated_net_reward, true)} />}
            {pv && <Line label="Max risk per trade" value={inr(pv.max_risk_amount)} />}
            {!pv?.risk_per_share && <div className="text-[13px] text-muted pt-1">Turn on Stop Loss and Take Profit to see risk and reward.</div>}
          </div>
        )}

        {pv?.warnings.filter((w) => !w.startsWith("Market is closed")).map((w) => <div key={w} className="text-[14px] text-[#b26a00]">{w}</div>)}
        {pv?.errors.map((w) => <div key={w} role="alert" className="text-[14px] text-down">{w}</div>)}
        {pvError && <div role="alert" className="text-[14px] text-down">{pvError}</div>}
        {result && <div role="status" className={`rounded-2xl px-4 py-3 text-[15px] animate-fade ${result.ok ? "bg-buybg/70 text-buy" : "bg-sellbg/70 text-sell"}`}>{result.text}</div>}
      </div>

      {pv?.market_open === false && (
        <div className="bg-soft px-6 py-4 text-[16px] text-[#555]">
          Market is closed. Market orders fill at the last traded price; limit and trigger orders activate when the market opens.
        </div>
      )}
      <div className={`border-t border-line px-6 py-4 flex items-center justify-between gap-4 bg-white ${sheet ? "sticky bottom-0 pb-[calc(16px+env(safe-area-inset-bottom))]" : ""}`}>
        <div className="text-[15px] leading-6 text-[#555]">
          <div>Est. balance: <span className="text-ink">{pv ? inr(pv.balance) : "₹0"}</span></div>
          {itype === "EQ" && product !== "INTRADAY"
            ? <div>Amount: <span className="text-ink">{pv?.order_value ? inr(pv.order_value) : "₹0"}</span></div>
            : <div title="Approximate fixed-percentage margin for F&O; full value for equity">Req margin: <span className="text-ink">{cash !== null ? inr(cash) : pv?.order_value ? inr(pv.order_value) : "₹0"}</span></div>}
          <div title="Estimate for the entry leg"><span className="underline underline-offset-2">Charges</span>: <span className="text-ink">{pv?.entry_charges ? inr(pv.entry_charges) : "₹0.00"}</span></div>
        </div>
        <button className={`btn min-w-[150px] py-4 text-[19px] text-white ${buy ? "bg-buy hover:bg-[#0f5c39]" : "bg-sell hover:bg-[#a82e27]"}`}
                disabled={!canPlace} onClick={place}>
          {busy ? "Placing…" : buy ? "Buy" : "Sell"}
        </button>
      </div>
    </div>
  );
}
