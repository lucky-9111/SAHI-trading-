import { LineChart, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BriefcaseArt } from "../components/art";
import { EmptyState, Flash, PageTitle, Segmented, Sheet, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, pnlClass, price } from "../utils/format";
import { keyOfPosition, positionPnl } from "../utils/liveKpi";
import { useLiveLtps, useOrdersChanged } from "../utils/liveSocket";
import { displayName } from "../utils/names";

export interface PositionRow {
  id: number; symbol: string; side: string; product: string; quantity: number; avg_price: string;
  current_price: string | null; invested_amount: string; stop_loss: string | null; target: string | null;
  unrealized_pnl: string | null; pnl_pct: string | null; strategy: string; opened_at: string;
  instrument_type: string; lot_size: number; expiry: string | null; chart_symbol: string; chart_exchange: string;
  exchange?: string; token?: string; entry_value?: string | null;
}
type View = "holdings" | "positions";
const isHolding = (p: PositionRow) => p.product === "DELIVERY" || p.product === "SWING";

function live(p: PositionRow, ltp?: number) {
  const pnl = positionPnl({ side: p.side, quantity: p.quantity, entry_value: p.entry_value, unrealized_pnl: p.unrealized_pnl }, ltp);
  const cur = ltp ?? (p.current_price ? Number(p.current_price) : null);
  const pct = pnl != null && Number(p.invested_amount) ? (pnl / Number(p.invested_amount)) * 100 : null;
  return { pnl, cur, pct };
}

function ActionSheet({ p, ltp, accountId, onClose, onDone }: { p: PositionRow; ltp?: number; accountId: number; onClose: () => void; onDone: (msg: string) => void }) {
  const [qty, setQty] = useState(String(p.quantity));
  const [sl, setSl] = useState(p.stop_loss ?? "");
  const [tg, setTg] = useState(p.target ?? "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/api/accounts/${accountId}/positions/${p.id}`;
  const { pnl, cur, pct } = live(p, ltp);
  const step = p.instrument_type === "EQ" ? 1 : p.lot_size;
  const run = async (fn: () => Promise<string>) => {
    setBusy(true); setErr("");
    try { onDone(await fn()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const exit = () => run(async () => {
    const n = Number(qty);
    const t = await api<{ net_pnl: string; exit_price: string }>(`${base}/exit`, { method: "POST", json: { quantity: n < p.quantity ? n : undefined } });
    return `Exited ${n} ${p.symbol} at ${inr(t.exit_price)} · net ${inr(t.net_pnl, true)}`;
  });
  const save = () => run(async () => {
    await api(base, { method: "PATCH", json: { stop_loss: sl || undefined, target: tg || undefined, clear_stop_loss: !sl && !!p.stop_loss, clear_target: !tg && !!p.target } });
    return `Updated stop loss / target of ${p.symbol}`;
  });
  return (
    <Sheet open onClose={onClose} label={`${p.symbol} position`}>
      <div className="px-6 pt-2 pb-6 space-y-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[19px] lg:text-[22px]">{displayName(p.symbol)}</div>
            <div className="text-[15px] lg:text-[16px] mt-1"><b className="font-medium">{price(cur)}</b> <span className="text-muted">LTP · {p.exchange}</span></div>
          </div>
          <span className={`rounded-full px-3.5 py-1.5 text-[14px] lg:text-[15px] ${p.side === "BUY" ? "bg-buybg text-buy" : "bg-sellbg text-sell"}`}>{p.side === "BUY" ? "Long" : "Short"}</span>
        </div>
        <div className="grid grid-cols-3 rounded-2xl bg-soft p-4 text-center">
          <div><div className="text-[12px] lg:text-[13px] text-muted">Qty</div><div className="text-[16px] lg:text-[17px] font-medium">{p.quantity}</div></div>
          <div><div className="text-[12px] lg:text-[13px] text-muted">Avg</div><div className="text-[16px] lg:text-[17px] font-medium">{price(p.avg_price)}</div></div>
          <div><div className="text-[12px] lg:text-[13px] text-muted">P&amp;L</div><div className={`text-[16px] lg:text-[17px] font-medium ${pnl != null ? pnlClass(pnl) : ""}`}>{pnl != null ? inr(pnl, true) : "—"}</div>
            {pct != null && <div className={`text-[11.5px] lg:text-[12px] ${pnlClass(pct)}`}>{pct.toFixed(2)}%</div>}</div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[16px] lg:text-[17px] text-muted">Exit quantity</span>
          <div className="flex items-center rounded-full bg-panel2 px-2 py-1.5">
            <button aria-label="Less" className="h-11 w-11 grid place-items-center rounded-full active:bg-white" onClick={() => setQty(String(Math.max(step, Number(qty) - step)))}><Minus size={20} /></button>
            <input aria-label="Exit quantity" className="w-20 bg-transparent text-center text-[16px] lg:text-[18px] font-medium outline-none" type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
            <button aria-label="More" className="h-11 w-11 grid place-items-center rounded-full active:bg-white" onClick={() => setQty(String(Math.min(p.quantity, Number(qty) + step)))}><Plus size={20} /></button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block"><span className="text-[13px] lg:text-[14px] text-muted">Stop loss</span><input className="input mt-1 text-right" type="number" step="0.05" value={sl} onChange={(e) => setSl(e.target.value)} placeholder="—" /></label>
          <label className="block"><span className="text-[13px] lg:text-[14px] text-muted">Target</span><input className="input mt-1 text-right" type="number" step="0.05" value={tg} onChange={(e) => setTg(e.target.value)} placeholder="—" /></label>
        </div>
        {err && <div role="alert" className="text-[13px] lg:text-[14px] text-down">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <button className="btn-outline py-3.5 text-[15px] lg:text-[16px]" disabled={busy} onClick={save}>Save SL / Target</button>
          <button className={`btn py-3.5 text-[15px] lg:text-[16px] text-white ${p.side === "BUY" ? "bg-sell" : "bg-buy"}`} disabled={busy || !(Number(qty) > 0)} onClick={exit}>
            {busy ? "Please wait…" : Number(qty) < p.quantity ? "Partial exit" : "Exit position"}
          </button>
        </div>
        <Link to={`/trade?symbol=${p.chart_symbol}&exchange=${p.chart_exchange}`} className="flex items-center justify-center gap-2 text-[14px] lg:text-[15px] text-muted"><LineChart size={17} /> Open chart</Link>
      </div>
    </Sheet>
  );
}

export default function PositionsPage() {
  const { accountId, refreshAccounts } = useAuth();
  const nav = useNavigate();
  const [rows, setRows] = useState<PositionRow[] | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [view, setView] = useState<View>("holdings");
  const [picked, setPicked] = useState<PositionRow | null>(null);

  const load = useCallback(() => {
    if (!accountId) return;
    api<PositionRow[]>(`/api/accounts/${accountId}/positions`).then((r) => {
      setRows(r); setError("");
      setView((v) => (r.length && !r.some((p) => (v === "holdings" ? isHolding(p) : !isHolding(p))) ? (v === "holdings" ? "positions" : "holdings") : v));
    }).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);

  const keys = useMemo(() => (rows ?? []).map((p) => keyOfPosition({ exchange: p.exchange, token: p.token })).filter(Boolean), [rows]);
  const ltps = useLiveLtps(keys);
  const ltpOf = (p: PositionRow) => ltps[keyOfPosition({ exchange: p.exchange, token: p.token })];
  const shown = (rows ?? []).filter((p) => (view === "holdings" ? isHolding(p) : !isHolding(p)));
  const totals = shown.reduce((a, p) => {
    const { pnl, cur } = live(p, ltpOf(p));
    a.invested += Number(p.invested_amount);
    a.pnl += pnl ?? 0;
    a.value += cur != null ? cur * p.quantity : Number(p.entry_value ?? 0);
    return a;
  }, { invested: 0, pnl: 0, value: 0 });

  if (!accountId) return <div className="p-6 text-muted">Create a portfolio first.</div>;
  return (
    <div className="lg:max-w-[820px]">
      <PageTitle>Portfolio</PageTitle>
      <div className="px-4 lg:px-0"><Segmented value={view} onChange={setView} items={[["holdings", "Holdings"], ["positions", "Positions"]]} /></div>
      {error && <div role="alert" className="mx-4 lg:mx-0 mt-3 rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] lg:text-[15px] text-sell">{error}</div>}
      {msg && <div role="status" className="mx-4 lg:mx-0 mt-3 rounded-2xl bg-buybg/70 px-4 py-3 text-[14px] lg:text-[15px] text-buy animate-fade">{msg}</div>}
      {rows === null ? <div className="px-4 lg:px-0"><Skeleton rows={4} /></div> : shown.length === 0 ? (
        <EmptyState art={<BriefcaseArt />} title={view === "holdings" ? "You don’t have any investments" : "You don’t have any open positions"}
                    text="Add funds to place your first trade." action={<button className="btn-pill" onClick={() => nav("/funds")}>Add money</button>} />
      ) : (
        <div className="px-4 lg:px-0 animate-fade">
          <div className="card mt-5 px-5 py-4">
            <div className="flex justify-between text-[13px] lg:text-[14px] text-muted"><span>{view === "holdings" ? "Current value" : "Position value"}</span><span>Invested</span></div>
            <div className="flex justify-between text-[17px] lg:text-[20px] font-medium mt-0.5"><Flash value={totals.value}>{inr(totals.value)}</Flash><span>{inr(totals.invested)}</span></div>
            <div className="h-px bg-line my-3" />
            <div className="flex justify-between items-baseline"><span className="text-[14px] lg:text-[15px] text-muted">Unrealised P&amp;L</span>
              <span className={`text-[16px] lg:text-[18px] font-medium ${pnlClass(totals.pnl)}`}><Flash value={totals.pnl}>{inr(totals.pnl, true)}</Flash>
                {totals.invested > 0 && <span className="text-[13px] lg:text-[14px] ml-1">({((totals.pnl / totals.invested) * 100).toFixed(2)}%)</span>}</span></div>
          </div>
          <div className="mt-2">
            {shown.map((p) => {
              const { pnl, cur, pct } = live(p, ltpOf(p));
              const lots = p.instrument_type !== "EQ" ? ` · ${p.quantity / p.lot_size} lot` : "";
              return (
                <button key={p.id} className="w-full text-left row active:bg-soft transition-colors" onClick={() => setPicked(p)}>
                  <div className="min-w-0">
                    <div className="row-name">{displayName(p.symbol)}</div>
                    <div className="row-sub">{p.side === "SELL" ? "Short · " : ""}{p.quantity} qty{lots} · avg {price(p.avg_price)}{p.stop_loss ? ` · SL ${price(p.stop_loss)}` : ""}</div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={`row-price ${pnl != null ? pnlClass(pnl) : ""}`}><Flash value={pnl}>{pnl != null ? inr(pnl, true) : "—"}</Flash></div>
                    <div className="row-chg text-muted">LTP <Flash value={cur}>{price(cur)}</Flash>{pct != null && <span className={`ml-1 ${pnlClass(pct)}`}>({pct.toFixed(2)}%)</span>}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
      {picked && (
        <ActionSheet p={picked} ltp={ltpOf(picked)} accountId={accountId} onClose={() => setPicked(null)}
                     onDone={(m) => { setPicked(null); setMsg(m); load(); refreshAccounts(); setTimeout(() => setMsg(""), 5000); }} />
      )}
    </div>
  );
}
