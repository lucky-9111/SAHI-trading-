import { Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { PriceLine } from "../charts/CandleChart";
import ChartView from "../charts/ChartView";
import OrderPanel from "../components/OrderPanel";
import StrategyContext, { useSymbolContext } from "../components/StrategyContext";
import type { QuoteRow } from "../components/market";
import { useAuth } from "../contexts/AuthContext";
import { ApiError, api } from "../services/api";
import { changeText, pnlClass, price } from "../utils/format";

const INDEX_NAMES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];

interface Future { instrument_id: number; symbol: string; exchange?: string; expiry: string; lot_size: number; ltp?: string; pct?: string }
interface Fno {
  underlying: string; is_index: boolean; spot: string | null; chart_symbol: string; chart_exchange: string;
  lot_size: number; futures: Future[]; option_expiries: string[];
}
interface Leg { instrument_id: number; symbol: string; lot_size: number; ltp: string | null; pct: string | null }
interface ChainRow { strike: string; ce: Leg | null; pe: Leg | null }
interface Chain { spot: string | null; atm_strike: string | null; lot_size: number; rows: ChainRow[] }
type Seg = "equity" | "futures" | "options";

const fmtDate = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

function Chips<T extends string>({ items, value, onChange }: { items: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(([v, l]) => <button key={v} className={v === value ? "chip-on" : "chip"} onClick={() => onChange(v)}>{l}</button>)}
    </div>
  );
}

function OptionChain({ chain, selected, onPick }: { chain: Chain; selected: string | null; onPick: (l: Leg, strike: string, kind: "CE" | "PE") => void }) {
  const cell = (l: Leg | null, strike: string, kind: "CE" | "PE") => (
    <td className="td text-right">
      {l ? (
        <button onClick={() => onPick(l, strike, kind)}
                className={`rounded-lg px-2 py-1 hover:bg-panel2 ${selected === l.symbol ? "ring-1 ring-slate-900 bg-panel2" : ""}`}>
          <span className="font-medium">{price(l.ltp)}</span>
          {l.pct && <span className={`ml-1 text-[11px] ${pnlClass(l.pct)}`}>{Number(l.pct) > 0 ? "+" : ""}{Number(l.pct).toFixed(1)}%</span>}
        </button>
      ) : <span className="text-muted">—</span>}
    </td>
  );
  return (
    <table className="w-full">
      <thead><tr className="border-b border-line">
        <th className="th text-right">Call (CE)</th><th className="th text-center">Strike</th><th className="th text-right">Put (PE)</th></tr></thead>
      <tbody>
        {chain.rows.map((r) => (
          <tr key={r.strike} className={`border-b border-line/60 ${r.strike === chain.atm_strike ? "bg-soft" : ""}`}>
            {cell(r.ce, r.strike, "CE")}
            <td className="td text-center font-semibold">{price(r.strike)}{r.strike === chain.atm_strike && <div className="text-[10px] text-muted">ATM</div>}</td>
            {cell(r.pe, r.strike, "PE")}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function TradePage() {
  const [params] = useSearchParams();
  const symbol = params.get("symbol");
  const exchange = params.get("exchange") ?? "NSE";
  const { accounts } = useAuth();
  const isCommodity = exchange === "MCX";
  // indices and commodities have no cash market of their own: they are traded through futures (and options for indices)
  const isIndex = !!symbol && (INDEX_NAMES.includes(symbol) || isCommodity);

  const [quote, setQuote] = useState<QuoteRow | null>(null);
  const [note, setNote] = useState("");
  const [fno, setFno] = useState<Fno | null>(null);
  const [seg, setSeg] = useState<Seg>("equity");
  const [futSym, setFutSym] = useState<string | null>(null);
  const [expiry, setExpiry] = useState<string | null>(null);
  const [chain, setChain] = useState<Chain | null>(null);
  const [leg, setLeg] = useState<{ symbol: string; lot: number; label: string } | null>(null);
  const [fnoError, setFnoError] = useState("");
  const [ctxKey, setCtxKey] = useState(0);
  const ctx = useSymbolContext(symbol ?? "", exchange, ctxKey);

  // Entry / SL / target lines on the equity chart (F&O contract prices differ from the underlying chart)
  const lines = useMemo<PriceLine[]>(() => {
    if (!ctx || seg !== "equity") return [];
    return ctx.positions.filter((p) => p.symbol === symbol).flatMap((p): PriceLine[] => [
      { price: Number(p.avg_price), color: "#2563eb", title: `${p.side === "BUY" ? "BUY" : "SELL"} ${p.quantity} · ${p.strategy}` },
      ...(p.stop_loss ? [{ price: Number(p.stop_loss), color: "#d93636", title: "SL", dashed: true }] : []),
      ...(p.target ? [{ price: Number(p.target), color: "#0b9d6c", title: "Target", dashed: true }] : []),
    ]);
  }, [ctx, seg, symbol]);

  // equity quote
  useEffect(() => {
    if (!symbol || isIndex) return;
    let stop = false;
    const load = () => api<QuoteRow>(`/api/market/quote/${symbol}?exchange=${exchange}`).then((q) => !stop && setQuote(q)).catch(() => {});
    setQuote(null); load();
    const t = setInterval(load, 10000);
    return () => { stop = true; clearInterval(t); };
  }, [symbol, exchange, isIndex]);

  // futures / options availability for this underlying
  useEffect(() => {
    if (!symbol) return;
    let stop = false;
    setFno(null); setFnoError(""); setLeg(null); setChain(null); setFutSym(null); setExpiry(null);
    setSeg(isIndex ? "futures" : "equity");
    api<Fno>(`/api/derivatives/${symbol}/expiries`).then((d) => {
      if (stop) return;
      setFno(d);
      setFutSym(d.futures[0]?.symbol ?? null);
      setExpiry(d.option_expiries[0] ?? null);
      if (isIndex) setSeg(d.futures.length ? "futures" : "options");
    }).catch((e) => { if (!stop && !(e instanceof ApiError && e.status === 404)) setFnoError(e.message); });
    return () => { stop = true; };
  }, [symbol, isIndex]);

  // option chain
  useEffect(() => {
    if (!symbol || seg !== "options" || !expiry) return;
    let stop = false;
    const load = () => api<Chain>(`/api/derivatives/${symbol}/chain?expiry=${expiry}`).then((c) => !stop && setChain(c)).catch((e) => !stop && setFnoError(e.message));
    load();
    const t = setInterval(load, 15000);
    return () => { stop = true; clearInterval(t); };
  }, [symbol, seg, expiry]);

  const addToWatchlist = async () => {
    try {
      const lists = await api<{ id: number }[]>("/api/watchlists");
      await api(`/api/watchlists/${lists[0].id}/items`, { method: "POST", json: { symbol, exchange } });
      setNote(`${symbol} added to your watchlist`);
    } catch (e) { setNote((e as Error).message); }
  };

  if (accounts.length === 0) return <div className="text-muted">Create a virtual portfolio on Home first.</div>;
  if (!symbol) {
    return (
      <div className="panel p-6 max-w-lg text-sm">
        <h1 className="text-lg font-semibold mb-2">Trade</h1>
        <p className="text-muted">Search for a stock (RELIANCE) or an index (NIFTY, BANKNIFTY) in the top bar to open its chart and order panel.</p>
      </div>
    );
  }

  const chartSymbol = seg === "equity" || !fno ? symbol : fno.chart_symbol;
  const chartExchange = seg === "equity" || !fno ? exchange : fno.chart_exchange;
  const fut = fno?.futures.find((f) => f.symbol === futSym);
  const spot = isIndex || seg !== "equity" ? fno?.spot : quote?.ltp;
  const segs: [Seg, string][] = [];
  if (!isIndex) segs.push(["equity", "Equity"]);
  if (fno?.futures.length) segs.push(["futures", "Futures"]);
  if (fno?.option_expiries.length) segs.push(["options", "Options"]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-1">
        <div>
          <h1 className="text-2xl font-semibold">{symbol}</h1>
          <div className="text-xs text-muted">{isCommodity ? "Commodity · MCX futures" : isIndex ? "Index · trade via futures or options" : `${exchange} · Equity`}</div>
        </div>
        {spot && (
          <div>
            <span className="text-2xl font-semibold">{price(spot)}</span>{" "}
            {!isIndex && seg === "equity" && quote && <span className={`text-sm ${pnlClass(quote.change ?? 0)}`}>{changeText(quote.change, quote.pct)}</span>}
            {(isIndex || seg !== "equity") && <span className="text-xs text-muted">{isCommodity ? "near-month futures" : "spot"}</span>}
          </div>
        )}
        <div className="flex-1" />
        {note && <span className="text-xs text-muted">{note}</span>}
        {!isIndex && <button className="btn-ghost" onClick={addToWatchlist}><Star size={15} /> Watchlist</button>}
      </div>

      {segs.length > 1 && <Chips items={segs} value={seg} onChange={(s) => { setSeg(s); setLeg(null); }} />}
      {fnoError && <div role="alert" className="text-sm text-down">{fnoError}</div>}

      <div className="grid xl:grid-cols-[1fr_390px] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          <div className="panel p-4"><ChartView key={chartSymbol} symbol={chartSymbol} exchange={chartExchange} height={seg === "options" ? 340 : 460} lines={lines} /></div>
          <StrategyContext ctx={ctx} />
          {seg === "options" && fno && (
            <div className="panel p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold">Option chain</h2>
                <select className="input !w-auto !rounded-full" value={expiry ?? ""} aria-label="Expiry"
                        onChange={(e) => { setExpiry(e.target.value); setChain(null); setLeg(null); }}>
                  {fno.option_expiries.map((e) => <option key={e} value={e}>{fmtDate(e)}</option>)}
                </select>
              </div>
              {chain ? <OptionChain chain={chain} selected={leg?.symbol ?? null}
                                    onPick={(l, strike, kind) => setLeg({ symbol: l.symbol, lot: l.lot_size, label: `${symbol} ${price(strike)} ${kind}` })} />
                : <div className="text-sm text-muted py-6">Loading option chain…</div>}
              <div className="text-xs text-muted">Showing strikes around the current spot. Click a price to trade that contract.</div>
            </div>
          )}
        </div>

        <div className="space-y-3">
          {seg === "equity" && <OrderPanel key={symbol} symbol={symbol} exchange={exchange} itype="EQ" pct={quote?.pct} onDone={() => setCtxKey((k) => k + 1)} />}
          {seg === "futures" && fno && (
            <>
              <div className="panel p-4 space-y-2">
                <div className="text-sm font-medium">Expiry</div>
                <Chips items={fno.futures.map((f): [string, string] => [f.symbol, fmtDate(f.expiry)])} value={futSym ?? ""} onChange={setFutSym} />
                {fut && <div className="text-xs text-muted">{fut.symbol} · lot {fut.lot_size}{fut.ltp ? ` · LTP ${price(fut.ltp)}` : ""}</div>}
              </div>
              {fut && <OrderPanel key={fut.symbol} symbol={fut.symbol} exchange={fut.exchange ?? "NFO"} lotSize={fut.lot_size} itype="FUT" pct={fut.pct} onDone={() => setCtxKey((k) => k + 1)} />}
            </>
          )}
          {seg === "options" && (leg
            ? <>
                <div className="panel px-4 py-3 text-sm"><span className="text-muted">Contract</span> <b>{leg.label}</b> <span className="text-muted">· expiry {expiry && fmtDate(expiry)}</span></div>
                <OrderPanel key={leg.symbol} symbol={leg.symbol} exchange="NFO" lotSize={leg.lot} itype="OPT" onDone={() => setCtxKey((k) => k + 1)} />
              </>
            : <div className="panel p-4 text-sm text-muted">Pick a call or put from the option chain to place an order.</div>)}
        </div>
      </div>
    </div>
  );
}
