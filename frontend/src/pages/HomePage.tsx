import { ArrowDownRight, ArrowUpRight, ChevronRight, IndianRupee, Minus, Search, Settings, User } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AreaChart from "../charts/AreaChart";
import { AppMark, ChartArt } from "../components/art";
import CreateAccount from "../components/CreateAccount";
import { ContractRow, INDEX_TRADE, IndexCard, StockRow, trendLabel, type ContractQuote, type IndexRow, type QuoteRow } from "../components/market";
import { openSearch } from "../components/search";
import { Chip, EmptyState, Flash, Segmented, Skeleton, Tabs, ViewAll } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { Dashboard } from "../types";
import { inr, pnlClass, price } from "../utils/format";
import { keyOfPosition, liveKpis, type LiveKpis } from "../utils/liveKpi";
import { useLiveLtps, useLiveRows, useLiveTick, useOrdersChanged } from "../utils/liveSocket";
import { displayName, readRecent } from "../utils/names";

type Tab = "fno" | "stocks" | "commodities" | "ipo" | "research" | "etfs";
const TAB_KEY = "sahi_home_tab";

function usePolled<T>(path: string | null, ms: number): { data: T | null; error: string } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) return;
    let stop = false;
    const load = () => { if (document.hidden) return; api<T>(path).then((d) => { if (!stop) { setData(d); setError(""); } }).catch((e) => { if (!stop) setError(e.message); }); };
    load();
    const t = setInterval(load, ms);
    return () => { stop = true; clearInterval(t); };
  }, [path, ms]);
  return { data, error };
}

function ErrorNote({ text }: { text: string }) {
  return <div role="alert" className="mx-4 lg:mx-0 my-4 rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] lg:text-[15px] text-sell">Market data unavailable: {text}</div>;
}

const Divider = () => <div className="h-px bg-line" />;

/* ---------------------------------------------------------------- header (phone) */
function MobileHeader() {
  return (
    <div className="lg:hidden flex items-center gap-3 px-4 pt-3 pb-2">
      <Link to="/" className="press"><div className="h-[40px] w-[40px] rounded-[13px] border border-line grid place-items-center"><AppMark size={25} /></div></Link>
      <button onClick={() => openSearch()} className="flex-1 min-w-0 h-[40px] rounded-full border border-line flex items-center gap-2.5 px-3.5 text-[15px] text-muted press">
        <Search size={19} strokeWidth={1.8} className="text-ink shrink-0" /><span className="truncate">Search SAHI</span>
      </button>
      <Link to="/funds" aria-label="Funds" className="h-[40px] w-[40px] shrink-0 grid place-items-center rounded-full border border-line press"><IndianRupee size={18} strokeWidth={1.7} /></Link>
      <Link to="/profile" aria-label="Profile" className="h-[40px] w-[40px] shrink-0 grid place-items-center rounded-full border border-line press"><User size={18} strokeWidth={1.7} /></Link>
    </div>
  );
}

/* ---------------------------------------------------------------- portfolio strip (live KPIs) */
function PortfolioStrip({ dash, kpi }: { dash: Dashboard; kpi: LiveKpis }) {
  return (
    <Link to="/positions" className="mx-4 lg:mx-0 mt-5 card flex items-center gap-4 px-5 py-4 press">
      <div className="flex-1 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <div><div className="text-[12px] lg:text-[13px] text-muted">Virtual capital</div><div className="text-[16px] lg:text-[17px] font-medium"><Flash value={kpi.totalCapital}>{inr(kpi.totalCapital)}</Flash></div></div>
        <div><div className="text-[12px] lg:text-[13px] text-muted">Total P&amp;L{kpi.allLive && dash.open_positions.length ? <span className="ml-1 text-up">●</span> : null}</div>
          <div className={`text-[16px] lg:text-[17px] font-medium ${pnlClass(kpi.total)}`}><Flash value={kpi.total}>{inr(kpi.total, true)}</Flash></div></div>
        <div className="hidden sm:block"><div className="text-[12px] lg:text-[13px] text-muted">Available</div><div className="text-[16px] lg:text-[17px] font-medium">{inr(kpi.available)}</div></div>
        <div className="hidden sm:block"><div className="text-[12px] lg:text-[13px] text-muted">Invested</div><div className="text-[16px] lg:text-[17px] font-medium">{inr(kpi.invested)}</div></div>
      </div>
      <ChevronRight size={20} className="text-muted" />
    </Link>
  );
}

/* ---------------------------------------------------------------- indices */
function useIndices() {
  const overview = usePolled<{ indices: IndexRow[]; market_open: boolean }>("/api/market/overview", 15000);
  const live = useLiveRows((overview.data?.indices ?? []).map((i) => ({ ...i, ltp: i.ltp as string | null, prev_close: i.prev_close ?? null, change: i.change as string | null, pct: i.pct as string | null })));
  const ORDER = ["NIFTY50", "SENSEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];
  const indices: IndexRow[] = live.map((i) => ({ ...i, ltp: i.ltp ?? "", change: i.change ?? "", pct: i.pct ?? "", trend: trendLabel(Number(i.pct)) }))
    .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  return { indices, open: overview.data?.market_open, error: overview.error, loaded: !!overview.data };
}

function IndicesRow({ indices, error, loaded, selected, onSelect, linkToTrade }: {
  indices: IndexRow[]; error: string; loaded: boolean; selected?: string; onSelect?: (k: string) => void; linkToTrade?: boolean;
}) {
  if (error && !loaded) return <ErrorNote text={error} />;
  return (
    <div className="flex gap-3 overflow-x-auto no-scrollbar px-4 lg:px-0 pb-1">
      {!loaded && [0, 1, 2].map((i) => <div key={i} className="skeleton shrink-0 w-[137px] h-[85px] lg:w-[210px] lg:h-[104px] rounded-card" />)}
      {indices.map((i) => (
        <IndexCard key={i.key} i={i} active={selected === i.key}
                   to={linkToTrade && INDEX_TRADE[i.key] ? `/trade?symbol=${INDEX_TRADE[i.key]}&exchange=NSE` : undefined}
                   onClick={onSelect ? () => onSelect(i.key) : undefined} />
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- recently viewed */
function RecentlyViewed() {
  const recent = useMemo(() => readRecent().filter((r) => r.exchange === "NSE").slice(0, 6), []);
  const [rows, setRows] = useState<Record<string, QuoteRow>>({});
  useEffect(() => {
    recent.forEach((r) => {
      if (INDEX_TRADE[r.symbol] || Object.values(INDEX_TRADE).includes(r.symbol)) return;
      api<QuoteRow>(`/api/market/quote/${r.symbol}?exchange=NSE`).then((q) => setRows((cur) => ({ ...cur, [r.symbol]: q }))).catch(() => {});
    });
  }, [recent]);
  const live = useLiveRows(Object.values(rows));
  if (!recent.length) return null;
  const by = Object.fromEntries(live.map((q) => [q.symbol, q]));
  return (
    <>
      <Divider />
      <section className="py-7">
        <h2 className="h2 px-4 lg:px-0 mb-4">Recently Viewed</h2>
        <div className="flex gap-3 overflow-x-auto no-scrollbar px-4 lg:px-0">
          {recent.map((r) => {
            const q = by[r.symbol];
            return (
              <Link key={r.symbol} to={`/trade?symbol=${r.symbol}&exchange=${r.exchange}`} className="card shrink-0 w-[46vw] max-w-[260px] px-5 py-4 press">
                <div className="text-[16px] lg:text-[17px] truncate">{displayName(r.symbol)}</div>
                <div className="mt-3 flex items-baseline gap-2"><span className="text-[17px] lg:text-[20px] font-medium"><Flash value={q?.ltp}>{q ? price(q.ltp) : "—"}</Flash></span><span className="text-[13px] lg:text-[14px] text-muted">{r.exchange}</span></div>
                <div className={`mt-1 text-[14px] lg:text-[15px] ${q?.change ? pnlClass(q.change) : "text-muted"}`}>{q?.change ? `${Number(q.change) > 0 ? "+" : ""}${price(q.change)} (${Math.abs(Number(q.pct)).toFixed(2)}%)` : " "}</div>
              </Link>
            );
          })}
        </div>
      </section>
    </>
  );
}

/* ---------------------------------------------------------------- Stocks tab */
function StocksTab({ dash, kpi }: { dash: Dashboard | null; kpi: LiveKpis | null }) {
  const { indices, error, loaded } = useIndices();
  const popular = usePolled<{ items: QuoteRow[] }>("/api/market/lists/popular", 15000);
  const live = useLiveRows(popular.data?.items ?? []);
  const [view, setView] = useState<"traded" | "gainers" | "losers">("traded");
  const [all, setAll] = useState(false);
  let rows = live.filter((r) => r.ltp !== null);
  if (view === "traded") rows = [...rows].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0));
  else {
    rows = [...rows].sort((a, b) => Number(b.pct) - Number(a.pct));
    if (view === "losers") rows.reverse();
    rows = rows.filter((r) => (view === "gainers" ? Number(r.pct) > 0 : Number(r.pct) < 0));
  }
  return (
    <div>
      {dash && kpi && <PortfolioStrip dash={dash} kpi={kpi} />}
      <section className="pt-7 pb-8">
        <h2 className="h2 px-4 lg:px-0 mb-4">Indices</h2>
        <IndicesRow indices={indices} error={error} loaded={loaded} linkToTrade />
      </section>
      <RecentlyViewed />
      <Divider />
      <section className="pt-7">
        <h2 className="h2 px-4 lg:px-0 mb-1">Trending Stocks</h2>
        <Tabs size="md" value={view} onChange={(v) => { setView(v); setAll(false); }}
              items={[{ value: "traded", label: "Most Traded", info: true }, { value: "gainers", label: "Top Gainers" }, { value: "losers", label: "Top Losers" }]} />
        <div className="px-4 lg:px-0">
          {popular.error && !popular.data ? <ErrorNote text={popular.error} /> : !popular.data ? <Skeleton rows={5} /> :
            rows.length === 0 ? <div className="py-10 text-center text-muted">Nothing to show right now.</div> :
              (all ? rows : rows.slice(0, 6)).map((r) => <StockRow key={r.symbol} r={r} />)}
          {rows.length > 6 && <ViewAll label={all ? "Show less" : "View all"} onClick={() => setAll(!all)} />}
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- F&O tab */
function TrendPill({ pct }: { pct: number }) {
  const t = trendLabel(pct);
  const up = /up/i.test(t), down = /down/i.test(t);
  const Icon = up ? ArrowUpRight : down ? ArrowDownRight : Minus;
  return (
    <div className="shrink-0 rounded-[20px] lg:rounded-[22px] border border-line px-3 py-2 lg:px-4 lg:py-2.5 flex items-center gap-2 lg:gap-2.5">
      <Icon size={22} className={`h-[19px] w-[19px] lg:h-[22px] lg:w-[22px] ${up ? "text-up" : down ? "text-down" : "text-muted"}`} />
      <div className="leading-tight">
        <div className={`text-[14.5px] lg:text-[16px] ${up ? "text-up" : down ? "text-down" : "text-muted"}`}>{t.replace("Strong ", "Strong ")}</div>
        <div className="text-[11.5px] lg:text-[13px] text-muted whitespace-nowrap">vs previous close</div>
      </div>
    </div>
  );
}

function FnoTab() {
  const { indices, error, loaded } = useIndices();
  const [sel, setSel] = useState("NIFTY50");
  const fno = usePolled<{ indices: ContractQuote[]; stocks: ContractQuote[] }>("/api/market/fno", 15000);
  const idxFut = useLiveRows(fno.data?.indices ?? []);
  const stkFut = useLiveRows(fno.data?.stocks ?? []);
  const cur = indices.find((i) => i.key === sel) ?? indices[0];
  const { fresh } = useLiveTick(cur?.exchange, cur?.token);
  return (
    <div>
      <section className="pt-7 pb-8">
        <div className="flex items-center justify-between px-4 lg:px-0 mb-4">
          <h2 className="h2">Indices</h2>
          {cur && INDEX_TRADE[cur.key] && <Link to={`/trade?symbol=${INDEX_TRADE[cur.key]}&exchange=NSE`} className="rounded-full border border-line px-4 py-2 text-[14px] lg:text-[15px] press">Option chain</Link>}
        </div>
        <IndicesRow indices={indices} error={error} loaded={loaded} selected={cur?.key} onSelect={setSel} />
      </section>
      <Divider />
      {cur && (
        <section className="pt-7 px-4 lg:px-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link to={INDEX_TRADE[cur.key] ? `/trade?symbol=${INDEX_TRADE[cur.key]}&exchange=NSE` : "#"} className="text-[16px] lg:text-[18px] underline underline-offset-4 decoration-1">{cur.key}</Link>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-[20px] lg:text-[28px] font-medium whitespace-nowrap"><Flash value={cur.ltp}>{price(cur.ltp)}</Flash></span>
                <span className={`text-[15px] lg:text-[17px] ${pnlClass(cur.change)}`}>({Math.abs(Number(cur.pct)).toFixed(2)}%)</span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-[14px] lg:text-[15px] text-muted">
                <span className={`h-2.5 w-2.5 rounded-full ${fresh ? "bg-down animate-pulse" : "bg-faint"}`} />{fresh ? "Live" : "Waiting for live ticks"}
              </div>
            </div>
            <TrendPill pct={Number(cur.pct)} />
          </div>
          <div className="flex gap-2.5 overflow-x-auto no-scrollbar mt-5 mb-3"><Chip on>Price</Chip></div>
          <AreaChart key={cur.key} symbol={cur.key} exchange={cur.exchange} prevClose={cur.prev_close ? Number(cur.prev_close) : null} />
        </section>
      )}
      <Divider />
      <section className="pt-7 px-4 lg:px-0">
        <h2 className="h2 mb-2">Index Futures</h2>
        {fno.error && !fno.data ? <ErrorNote text={fno.error} /> : !fno.data ? <Skeleton rows={4} /> : idxFut.map((r) => <ContractRow key={r.contract} r={r} />)}
      </section>
      <Divider />
      <section className="pt-7 px-4 lg:px-0">
        <h2 className="h2 mb-2">Stock Futures</h2>
        {!fno.data ? <Skeleton rows={4} /> : stkFut.map((r) => <ContractRow key={r.contract} r={r} />)}
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- Commodities tab */
function CommoditiesTab() {
  const raw = usePolled<{ items: ContractQuote[]; market_open: boolean }>("/api/market/commodities", 15000);
  const items = useLiveRows(raw.data?.items ?? []);
  const [all, setAll] = useState(false);
  return (
    <section className="pt-7 px-4 lg:px-0">
      <div className="flex items-center justify-between mb-2">
        <h2 className="h2">Top Traded Commodity</h2>
        <span className={`rounded-full border border-line px-4 py-2 text-[13px] lg:text-[14px] ${raw.data?.market_open ? "text-up" : "text-muted"}`}>
          {raw.data ? (raw.data.market_open ? "MCX open" : "MCX closed") : "MCX"}
        </span>
      </div>
      {raw.error && !raw.data ? <ErrorNote text={raw.error} /> : !raw.data ? <Skeleton rows={6} /> :
        (all ? items : items.slice(0, 8)).map((r) => <ContractRow key={r.contract} r={r} icon />)}
      {items.length > 8 && <ViewAll label={all ? "Show less" : "View all"} onClick={() => setAll(!all)} />}
      <p className="text-[12px] lg:text-[13px] text-muted pb-6 pt-2">Nearest-expiry future of each commodity. Gold is quoted per 10 g (1 lot of GOLD = 100 units).</p>
    </section>
  );
}

/* ---------------------------------------------------------------- IPO / Research (no data source) */
function IpoTab() {
  const [v, setV] = useState<"open" | "applied" | "closed" | "upcoming">("open");
  return (
    <section className="pt-6 px-4 lg:px-0">
      <Segmented value={v} onChange={setV} items={[["open", "Open"], ["applied", "Applied"], ["closed", "Closed"], ["upcoming", "Upcoming"]]} />
      <EmptyState art={<ChartArt />} title="No IPO data is connected yet" text="IPOs will appear here once an IPO data source is added." />
    </section>
  );
}

function ResearchTab() {
  const [v, setV] = useState<"options" | "stocks">("options");
  return (
    <section className="pt-6 px-4 lg:px-0">
      <Segmented value={v} onChange={setV} items={[["options", "Options"], ["stocks", "Stocks"]]} />
      <EmptyState art={<ChartArt />} title="No research recommendations" text="There is no research feed in paper-trading mode." />
    </section>
  );
}

/* ---------------------------------------------------------------- ETFs */
const ETF_CATS: Record<string, { label: string; chips?: Record<string, string[]>; symbols?: string[] }> = {
  indices: { label: "Indices", chips: { "Nifty 50": ["NIFTYBEES", "SETFNIF50", "NIFTYIETF", "HDFCNIFTY"], "Nifty Bank": ["BANKBEES", "SETFNIFBK", "BANKIETF", "PSUBNKBEES"], "Others": ["JUNIORBEES", "ITBEES"] } },
  liquid: { label: "Liquid", symbols: ["LIQUIDBEES", "LIQUIDIETF"] },
  gold: { label: "Gold", symbols: ["GOLDBEES", "HDFCGOLD", "GOLDIETF"] },
  silver: { label: "Silver", symbols: ["SILVERBEES", "SILVERIETF", "HDFCSILVER"] },
};

function EtfsTab() {
  const raw = usePolled<{ items: QuoteRow[] }>("/api/market/lists/etfs", 15000);
  const items = useLiveRows(raw.data?.items ?? []);
  const [cat, setCat] = useState("indices");
  const [chip, setChip] = useState("Nifty 50");
  const c = ETF_CATS[cat];
  const want = c.chips ? c.chips[chip] ?? [] : c.symbols ?? [];
  const rows = items.filter((r) => want.includes(r.symbol));
  return (
    <section className="pt-7">
      <h2 className="h2 px-4 lg:px-0 mb-1">Popular Categories</h2>
      <Tabs size="md" value={cat} onChange={(v) => { setCat(v); setChip(ETF_CATS[v].chips ? Object.keys(ETF_CATS[v].chips!)[0] : ""); }}
            items={Object.entries(ETF_CATS).map(([k, v]) => ({ value: k, label: v.label, info: k === "indices" }))} />
      {c.chips && (
        <div className="flex gap-2.5 overflow-x-auto no-scrollbar px-4 lg:px-0 pt-5">
          {Object.keys(c.chips).map((k) => <Chip key={k} on={chip === k} onClick={() => setChip(k)}>{k}</Chip>)}
        </div>
      )}
      <div className="px-4 lg:px-0">
        {raw.error && !raw.data ? <ErrorNote text={raw.error} /> : !raw.data ? <Skeleton rows={3} /> :
          rows.length ? rows.map((r) => <StockRow key={r.symbol} r={r} />) : <div className="py-10 text-center text-muted">No ETF in this category yet.</div>}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- page */
export default function HomePage() {
  const { accountId, accounts } = useAuth();
  const [tab, setTabState] = useState<Tab>(() => { try { return (localStorage.getItem(TAB_KEY) as Tab) || "stocks"; } catch { return "stocks"; } });
  const setTab = (t: Tab) => { setTabState(t); try { localStorage.setItem(TAB_KEY, t); } catch { /* ignore */ } };
  const [dash, setDash] = useState<Dashboard | null>(null);

  const load = useCallback(() => {
    if (!accountId) return;
    api<Dashboard>(`/api/accounts/${accountId}/dashboard`).then(setDash).catch(() => {});
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);
  const posKeys = useMemo(() => (dash?.open_positions ?? []).map(keyOfPosition).filter(Boolean), [dash]);
  const ltps = useLiveLtps(posKeys);
  const kpi = dash ? liveKpis(dash, ltps) : null;

  if (accounts.length === 0) {
    return (
      <div className="px-4 lg:px-0 py-6 space-y-4">
        <MobileHeader />
        <h1 className="page-title">Welcome to SAHI Trading</h1>
        <p className="text-[15px] lg:text-[16px] text-muted">Create your first virtual portfolio to start paper trading.</p>
        <CreateAccount />
      </div>
    );
  }
  return (
    <div className="lg:max-w-[860px]">
      <MobileHeader />
      <div className="sticky top-0 lg:top-[76px] z-20 bg-white">
        <Tabs value={tab} onChange={setTab}
              items={[{ value: "fno", label: "F&O" }, { value: "stocks", label: "Stocks" }, { value: "commodities", label: "Commodities" },
                      { value: "ipo", label: "IPO" }, { value: "research", label: "Research" }, { value: "etfs", label: "ETFs" }]}
              right={<Link to="/settings" aria-label="Settings" className="shrink-0 self-center ml-1 h-[38px] w-[46px] grid place-items-center rounded-l-full bg-panel2 lg:hidden press shadow-[-12px_0_12px_#fff]"><Settings size={24} strokeWidth={1.6} /></Link>} />
      </div>
      <div key={tab} className="animate-fade">
        {tab === "stocks" && <StocksTab dash={dash} kpi={kpi} />}
        {tab === "fno" && <FnoTab />}
        {tab === "commodities" && <CommoditiesTab />}
        {tab === "ipo" && <IpoTab />}
        {tab === "research" && <ResearchTab />}
        {tab === "etfs" && <EtfsTab />}
      </div>
      {/* the reference app's peach strip above the bottom bar */}
      <div className="lg:hidden fixed inset-x-0 bottom-[calc(62px+env(safe-area-inset-bottom))] z-30 bg-peach px-4 py-[7px] text-[13px] text-ink truncate">
        You are on <b className="font-semibold">SAHI Paper Trading</b> · virtual money only
      </div>
      <div className="lg:hidden h-12" />
    </div>
  );
}
