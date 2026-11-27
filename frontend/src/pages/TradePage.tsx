import { Bookmark, BookmarkCheck, ChartLine, ChevronRight, Link2, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { PriceLine } from "../charts/CandleChart";
import ChartView from "../charts/ChartView";
import { ChartArt } from "../components/art";
import FuturesSheet, { futureName, type FutureRow } from "../components/FuturesSheet";
import type { QuoteRow } from "../components/market";
import OrderPanel from "../components/OrderPanel";
import { openSearch } from "../components/search";
import StrategyContext, { useSymbolContext } from "../components/StrategyContext";
import { BackBar, Chip, EmptyState, Flash, Sheet, Tabs } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { ApiError, api } from "../services/api";
import { changeText, pnlClass, price } from "../utils/format";
import { useLiveRows, useLiveTick } from "../utils/liveSocket";
import { displayName, pushRecent } from "../utils/names";

const INDEX_NAMES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];

type Future = FutureRow;
interface Fno {
  underlying: string; is_index: boolean; spot: string | null; chart_symbol: string; chart_exchange: string;
  lot_size: number; futures: Future[]; option_expiries: string[];
}
interface Leg { instrument_id: number; symbol: string; lot_size: number; ltp: string | null; pct: string | null; token?: string; exchange?: string }
interface ChainRow { strike: string; ce: Leg | null; pe: Leg | null }
interface Chain { spot: string | null; atm_strike: string | null; lot_size: number; rows: ChainRow[] }
type Seg = "equity" | "futures" | "options";
interface Contract { symbol: string; exchange: string; itype: "EQ" | "FUT" | "OPT"; lot: number; token?: string; pct?: string | null; label: string }

const fmtDate = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });

function OptionChain({ chain, selected, onPick }: { chain: Chain; selected: string | null; onPick: (l: Leg, strike: string, kind: "CE" | "PE") => void }) {
  const cell = (l: Leg | null, strike: string, kind: "CE" | "PE") => (
    <td className="py-1.5 text-center">
      {l ? (
        <button onClick={() => onPick(l, strike, kind)}
                className={`rounded-xl px-2.5 py-2 w-full press ${selected === l.symbol ? "bg-ink text-white" : "active:bg-soft"}`}>
          <div className="text-[15px] lg:text-[16px] font-medium">{price(l.ltp)}</div>
          {l.pct && <div className={`text-[11.5px] lg:text-[12px] ${selected === l.symbol ? "text-white/80" : pnlClass(l.pct)}`}>{Number(l.pct) > 0 ? "+" : ""}{Number(l.pct).toFixed(1)}%</div>}
        </button>
      ) : <span className="text-faint">—</span>}
    </td>
  );
  return (
    <table className="w-full">
      <thead><tr className="text-[12px] lg:text-[13px] text-muted"><th className="py-2 font-normal">Call</th><th className="py-2 font-normal">Strike</th><th className="py-2 font-normal">Put</th></tr></thead>
      <tbody>
        {chain.rows.map((r) => (
          <tr key={r.strike} className={`border-t border-line ${r.strike === chain.atm_strike ? "bg-soft" : ""}`}>
            {cell(r.ce, r.strike, "CE")}
            <td className="py-1.5 text-center text-[15px] lg:text-[16px] font-medium">{price(r.strike)}{r.strike === chain.atm_strike && <div className="text-[10.5px] lg:text-[11px] text-muted font-normal">ATM</div>}</td>
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
  const futParam = params.get("fut");        // a futures contract of this stock picked from the Futures sheet
  const viewParam = params.get("view");      // "options": open on the option chain
  const nav = useNavigate();
  const stockUrl = `/trade?symbol=${encodeURIComponent(symbol ?? "")}&exchange=${exchange}`;
  const { accounts } = useAuth();
  const isCommodity = exchange === "MCX";
  const isIndex = !!symbol && (INDEX_NAMES.includes(symbol) || isCommodity);

  const [quote, setQuote] = useState<QuoteRow | null>(null);
  const [note, setNote] = useState("");
  const [fno, setFno] = useState<Fno | null>(null);
  const [seg, setSeg] = useState<Seg>("equity");
  const [futSym, setFutSym] = useState<string | null>(null);
  const [expiry, setExpiry] = useState<string | null>(null);
  const [chain, setChain] = useState<Chain | null>(null);
  const [leg, setLeg] = useState<Leg & { label: string } | null>(null);
  const [fnoError, setFnoError] = useState("");
  const [ctxKey, setCtxKey] = useState(0);
  const [sheet, setSheet] = useState<"BUY" | "SELL" | null>(null);
  const [saved, setSaved] = useState(false);
  const [futuresOpen, setFuturesOpen] = useState(false);
  const ctx = useSymbolContext(symbol ?? "", exchange, ctxKey);

  useEffect(() => { if (symbol) pushRecent(symbol, exchange); }, [symbol, exchange]);

  const lines = useMemo<PriceLine[]>(() => {
    if (!ctx || seg !== "equity") return [];
    return ctx.positions.filter((p) => p.symbol === symbol).flatMap((p): PriceLine[] => [
      { price: Number(p.avg_price), color: "#2563eb", title: `${p.side === "BUY" ? "BUY" : "SELL"} ${p.quantity} · ${p.strategy}` },
      ...(p.stop_loss ? [{ price: Number(p.stop_loss), color: "#d33a3a", title: "SL", dashed: true }] : []),
      ...(p.target ? [{ price: Number(p.target), color: "#1a9a6b", title: "Target", dashed: true }] : []),
    ]);
  }, [ctx, seg, symbol]);

  useEffect(() => {
    if (!symbol || isIndex) return;
    let stop = false;
    const load = () => api<QuoteRow>(`/api/market/quote/${symbol}?exchange=${exchange}`).then((q) => !stop && setQuote(q)).catch(() => {});
    setQuote(null); load();
    const t = setInterval(load, 15000);
    return () => { stop = true; clearInterval(t); };
  }, [symbol, exchange, isIndex]);
  const [liveQuote] = useLiveRows(quote ? [quote] : []);

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

  // the URL decides the view of a stock page: its chart, one of its futures, or its option chain
  useEffect(() => {
    if (!fno || isIndex) return;
    if (futParam && fno.futures.some((f) => f.symbol === futParam)) { setFutSym(futParam); setSeg("futures"); }
    else if (viewParam === "options" && fno.option_expiries.length) setSeg("options");
    else setSeg("equity");
    setLeg(null);
  }, [fno, futParam, viewParam, isIndex]);

  useEffect(() => {
    if (!symbol || seg !== "options" || !expiry) return;
    let stop = false;
    const load = () => api<Chain>(`/api/derivatives/${symbol}/chain?expiry=${expiry}`).then((c) => !stop && setChain(c)).catch((e) => !stop && setFnoError(e.message));
    load();
    const t = setInterval(load, 15000);
    return () => { stop = true; clearInterval(t); };
  }, [symbol, seg, expiry]);

  const fut = fno?.futures.find((f) => f.symbol === futSym);
  const futLive = useLiveTick(fut?.exchange ?? "NFO", fut?.token);
  // contract page: a stock's future opened from the Futures sheet (indices keep their own Futures tab)
  const futureMode = !isIndex && !!futParam && !!fut && fut.symbol === futParam && seg === "futures";
  const futLtp = futLive.fresh && futLive.tick ? futLive.tick.ltp : fut?.ltp != null ? Number(fut.ltp) : null;
  const futPrev = fut?.prev_close ? Number(fut.prev_close) : null;
  const futChange = futLtp != null && futPrev ? futLtp - futPrev : fut?.change != null ? Number(fut.change) : null;
  const futPct = futLtp != null && futPrev && futChange != null ? (futChange / futPrev) * 100 : fut?.pct != null ? Number(fut.pct) : null;
  // a stock's future or option chain is a sub-view with its own URL (back button returns to the stock)
  const stockSubView = !isIndex && (futureMode || seg === "options");
  const openFuture = (f: Future) => nav(`${stockUrl}&fut=${encodeURIComponent(f.symbol)}`, { replace: stockSubView });
  const openOptions = () => { if (seg !== "options") nav(`${stockUrl}&view=options`, { replace: stockSubView }); };

  const addToWatchlist = async () => {
    try {
      const lists = await api<{ id: number }[]>("/api/watchlists");
      await api(`/api/watchlists/${lists[0].id}/items`, { method: "POST", json: { symbol, exchange } });
      setSaved(true); setNote(`${displayName(symbol ?? "")} added to your watchlist`);
    } catch (e) { setNote((e as Error).message); }
    setTimeout(() => setNote(""), 3500);
  };

  if (accounts.length === 0) return <div className="p-6 text-muted">Create a virtual portfolio on Home first.</div>;
  if (!symbol) {
    return (
      <div className="lg:max-w-[720px]">
        <div className="px-4 lg:px-0 pt-5 pb-2"><h1 className="page-title">Trade</h1></div>
        <EmptyState art={<ChartArt />} title="Search a stock, index or commodity" text="Its chart and order panel open here."
                    action={<button className="btn-pill" onClick={() => openSearch()}>Search</button>} />
      </div>
    );
  }

  const chartSymbol = futureMode ? fut!.symbol : seg === "equity" || !fno ? symbol : fno.chart_symbol;
  const chartExchange = futureMode ? fut!.exchange ?? "NFO" : seg === "equity" || !fno ? exchange : fno.chart_exchange;
  const headPrice = futureMode ? futLtp : isIndex ? (isCommodity && futLive.fresh && futLive.tick ? futLive.tick.ltp : fno?.spot) : liveQuote?.ltp;
  const tabs: { value: Seg; label: string }[] = [];
  if (!isIndex) tabs.push({ value: "equity", label: "Chart" });
  if (fno?.futures.length) tabs.push({ value: "futures", label: "Futures" });
  if (fno?.option_expiries.length) tabs.push({ value: "options", label: "Options" });

  const contract: Contract | null =
    seg === "equity" ? { symbol, exchange, itype: "EQ", lot: 1, token: liveQuote?.token, pct: liveQuote?.pct, label: displayName(symbol) }
      : seg === "futures" && fut ? { symbol: fut.symbol, exchange: fut.exchange ?? "NFO", itype: "FUT", lot: fut.lot_size, token: fut.token, pct: fut.pct, label: fut.symbol }
        : seg === "options" && leg ? { symbol: leg.symbol, exchange: leg.exchange ?? "NFO", itype: "OPT", lot: leg.lot_size, token: leg.token, pct: leg.pct, label: leg.label }
          : null;
  const panel = (side: "BUY" | "SELL", inSheet: boolean) => contract && (
    <OrderPanel key={contract.symbol + side + inSheet} symbol={contract.symbol} exchange={contract.exchange} lotSize={contract.lot} itype={contract.itype}
                pct={contract.pct} token={contract.token} initialSide={side} sheet={inSheet}
                onDone={() => setCtxKey((k) => k + 1)} />
  );

  const title = (
    <div className="min-w-0">
      <button onClick={() => openSearch()} className="text-[15.5px] lg:text-[26px] leading-tight lg:leading-normal underline underline-offset-4 decoration-1 truncate max-w-full text-left">
        {futureMode && fno ? futureName(fno.underlying, fut!.expiry) : displayName(symbol)}
      </button>
      <div className="flex items-baseline gap-1.5 lg:gap-2 text-[17px] lg:text-[19px] whitespace-nowrap">
        <span className="font-medium"><Flash value={headPrice}>{headPrice != null ? price(headPrice) : "—"}</Flash></span>
        {futureMode
          ? futChange != null && <span className={`text-[15px] lg:text-[19px] ${pnlClass(futChange)}`}>{changeText(futChange.toFixed(2), futPct != null ? futPct.toFixed(2) : null)}</span>
          : !isIndex && liveQuote && <span className={`text-[15px] lg:text-[19px] ${pnlClass(liveQuote.change ?? 0)}`}>{changeText(liveQuote.change, liveQuote.pct)}</span>}
        <span className="text-muted text-[14px] lg:text-[15px] truncate">{isCommodity ? "MCX · near month" : isIndex ? "Index" : exchange}</span>
      </div>
    </div>
  );

  return (
    <div className="pb-[calc(84px+env(safe-area-inset-bottom))] lg:pb-0">
      {/* phone header */}
      <div className="lg:hidden">
        <BackBar title={title} right={<>
          <button aria-label="Search" className="h-10 w-10 grid place-items-center" onClick={() => openSearch()}><Search size={22} strokeWidth={1.7} /></button>
          {!isIndex && <button aria-label="Add to watchlist" className="h-10 w-10 grid place-items-center" onClick={addToWatchlist}>{saved ? <BookmarkCheck size={22} /> : <Bookmark size={22} strokeWidth={1.7} />}</button>}
        </>} />
      </div>
      {/* desktop header */}
      <div className="hidden lg:flex items-end justify-between gap-4 mb-2">
        {title}
        {!isIndex && <button className="btn-ghost" onClick={addToWatchlist}>{saved ? <BookmarkCheck size={17} /> : <Bookmark size={17} />} Watchlist</button>}
      </div>
      {note && <div role="status" className="mx-4 lg:mx-0 mb-2 rounded-2xl bg-buybg/70 px-4 py-2.5 text-[14px] lg:text-[15px] text-buy animate-fade">{note}</div>}

      {tabs.length > 1 && isIndex && <Tabs value={seg} onChange={(s) => { setSeg(s); setLeg(null); }} items={tabs} />}
      {fnoError && <div role="alert" className="mx-4 lg:mx-0 mt-2 text-[13px] lg:text-[14px] text-down">{fnoError}</div>}

      <div className="lg:grid lg:grid-cols-[1fr_420px] lg:gap-6 lg:items-start lg:mt-5">
        <div className="min-w-0 space-y-5">
          <div className="pt-3 lg:pt-0 lg:card lg:p-4"><ChartView key={chartSymbol + seg} symbol={chartSymbol} exchange={chartExchange} height={seg === "options" ? 300 : 420} lines={lines} /></div>

          {/* future / option chain of a stock: the stock itself, tap to go back to it */}
          {stockSubView && (
            <button onClick={() => nav(stockUrl)} className="w-full flex items-center gap-3 px-4 lg:px-0 py-4 border-y border-line text-left active:bg-soft">
              <span className="text-[16px] lg:text-[18px] font-medium flex-1 truncate">{symbol}</span>
              <span className="text-[16px] lg:text-[17px] tabular-nums">{liveQuote?.ltp != null ? price(liveQuote.ltp) : "—"}</span>
              {liveQuote && <span className={`text-[15px] lg:text-[16px] tabular-nums ${pnlClass(liveQuote.change ?? 0)}`}>{changeText(liveQuote.change, liveQuote.pct)}</span>}
              <ChevronRight size={20} className="text-muted shrink-0" />
            </button>
          )}

          {/* tools under the chart (stocks with F&O) */}
          {!isIndex && fno && (fno.futures.length > 0 || fno.option_expiries.length > 0) && (
            <div className="flex gap-3 overflow-x-auto no-scrollbar px-4 lg:px-0">
              {fno.futures.length > 0 && (
                <button onClick={() => setFuturesOpen(true)} className="shrink-0 w-[78px] lg:w-[96px] rounded-[14px] lg:rounded-2xl bg-panel2 px-1.5 lg:px-2 py-2 lg:py-2.5 flex flex-col items-center gap-1 lg:gap-1.5 press active:brightness-95">
                  <ChartLine size={24} strokeWidth={1.6} className="h-[21px] w-[21px] lg:h-6 lg:w-6" />
                  <span className="text-[12px] lg:text-[13.5px] leading-tight">Futures</span>
                </button>
              )}
              {fno.option_expiries.length > 0 && (
                <button onClick={() => { openOptions(); window.scrollTo({ top: 0, behavior: "smooth" }); }} className="shrink-0 w-[78px] lg:w-[96px] rounded-[14px] lg:rounded-2xl bg-panel2 px-1.5 lg:px-2 py-2 lg:py-2.5 flex flex-col items-center gap-1 lg:gap-1.5 press active:brightness-95">
                  <span className="h-[21px] w-[21px] lg:h-6 lg:w-6 rounded-md bg-brand text-white grid place-items-center"><Link2 size={15} strokeWidth={2} /></span>
                  <span className="text-[12px] lg:text-[13.5px] leading-tight">Option Chain</span>
                </button>
              )}
            </div>
          )}

          {seg === "futures" && fno && !futureMode && (
            <div className="px-4 lg:px-0 space-y-3">
              <div className="text-[14px] lg:text-[15px] text-muted">Expiry</div>
              <div className="flex gap-2.5 overflow-x-auto no-scrollbar">
                {fno.futures.map((f) => <Chip key={f.symbol} on={f.symbol === futSym} onClick={() => setFutSym(f.symbol)}>{fmtDate(f.expiry)}</Chip>)}
              </div>
              {fut && <div className="text-[14px] lg:text-[15px] text-muted">{futureName(fno.underlying, fut.expiry)} · lot {fut.lot_size} · LTP <b className="text-ink font-medium"><Flash value={futLive.fresh && futLive.tick ? futLive.tick.ltp : fut.ltp}>{price(futLive.fresh && futLive.tick ? futLive.tick.ltp : fut.ltp)}</Flash></b></div>}
            </div>
          )}

          {seg === "options" && fno && (
            <div className="px-4 lg:px-0">
              <div className="flex gap-2.5 overflow-x-auto no-scrollbar pb-3">
                {fno.option_expiries.slice(0, 8).map((e) => <Chip key={e} on={e === expiry} onClick={() => { setExpiry(e); setChain(null); setLeg(null); }}>{fmtDate(e)}</Chip>)}
              </div>
              {chain ? <OptionChain chain={chain} selected={leg?.symbol ?? null}
                                    onPick={(l, strike, kind) => { setLeg({ ...l, label: `${symbol} ${price(strike)} ${kind}` }); if (window.innerWidth < 1024) setSheet("BUY"); }} />
                : <div className="skeleton h-64 w-full" />}
              <div className="text-[12px] lg:text-[13px] text-muted pt-3">Tap a price to trade that contract.</div>
            </div>
          )}

          <div className="px-4 lg:px-0"><StrategyContext ctx={ctx} /></div>
        </div>

        {/* desktop order panel */}
        <div className="hidden lg:block lg:sticky lg:top-[96px]">
          {contract ? panel("BUY", false) : <div className="card p-6 text-[14px] lg:text-[15px] text-muted">Pick a call or put from the option chain to place an order.</div>}
        </div>
      </div>

      {/* phone: Buy / Sell bar */}
      <div className="lg:hidden fixed inset-x-0 bottom-0 z-30 bg-white border-t border-line px-4 pt-3 pb-[calc(12px+env(safe-area-inset-bottom))] grid grid-cols-2 gap-3">
        {contract ? (
          <>
            <button className="btn py-3 lg:py-4 text-[16px] lg:text-[18px] text-white bg-buy" onClick={() => setSheet("BUY")}>Buy</button>
            <button className="btn py-3 lg:py-4 text-[16px] lg:text-[18px] text-white bg-sell" onClick={() => setSheet("SELL")}>Sell</button>
          </>
        ) : <div className="col-span-2 text-center text-[14px] lg:text-[15px] text-muted py-3">Pick a strike from the option chain</div>}
      </div>
      {fno && (
        <FuturesSheet open={futuresOpen} onClose={() => setFuturesOpen(false)} underlying={fno.underlying} futures={fno.futures}
                      spot={liveQuote?.ltp ? Number(liveQuote.ltp) : fno.spot ? Number(fno.spot) : null}
                      onPick={(f) => {
                        setFuturesOpen(false); window.scrollTo({ top: 0, behavior: "smooth" });
                        if (isIndex) { setFutSym(f.symbol); setSeg("futures"); setLeg(null); } else openFuture(f);
                      }} />
      )}
      <Sheet open={!!sheet && !!contract} onClose={() => setSheet(null)} label="Place order">
        {sheet && panel(sheet, true)}
      </Sheet>
    </div>
  );
}
