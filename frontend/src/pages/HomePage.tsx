import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import ChartView from "../charts/ChartView";
import CreateAccount from "../components/CreateAccount";
import { ContractRow, IndexCard, StockRow, TrendTile, trendLabel, type ContractQuote, type IndexRow, type QuoteRow } from "../components/market";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { Dashboard } from "../types";
import { inr, pnlClass } from "../utils/format";
import { keyOfPosition, liveKpis, type LiveKpis } from "../utils/liveKpi";
import { useLiveLtps, useLiveRows, useOrdersChanged } from "../utils/liveSocket";

const TABS = ["F&O", "Stocks", "Commodities", "IPO", "Research", "ETFs"] as const;
type Tab = (typeof TABS)[number];

const UNSUPPORTED: Record<string, string> = {
  IPO: "IPO tracking is not available yet. There is no IPO data source connected.",
  Research: "Research content is not available yet. There is no research data source connected.",
};

function Stat({ label, value, cls = "" }: { label: string; value: ReactNode; cls?: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold ${cls}`}>{value}</div>
    </div>
  );
}

function usePolled<T>(path: string, ms: number): { data: T | null; error: string } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stop = false;
    const load = () => api<T>(path).then((d) => { if (!stop) { setData(d); setError(""); } })
      .catch((e) => { if (!stop) setError(e.message); });
    load();
    const t = setInterval(load, ms);
    return () => { stop = true; clearInterval(t); };
  }, [path, ms]);
  return { data, error };
}

function ErrorNote({ text }: { text: string }) {
  return (
    <div role="alert" className="panel p-4 text-sm">
      <div className="font-medium text-down">Market data unavailable</div>
      <div className="text-muted mt-1">{text}</div>
    </div>
  );
}

function StocksTab({ dash, kpi }: { dash: Dashboard | null; kpi: LiveKpis | null }) {
  const overview = usePolled<{ indices: IndexRow[]; market_open: boolean }>("/api/market/overview", 15000);
  const popular = usePolled<{ items: QuoteRow[] }>("/api/market/lists/popular", 15000);
  const [chartKey, setChartKey] = useState("NIFTY50");
  const [view, setView] = useState<"popular" | "gainers" | "losers">("popular");

  const liveIdx = useLiveRows((overview.data?.indices ?? []).map((i) => ({ ...i, ltp: i.ltp as string | null, prev_close: i.prev_close ?? null, change: i.change as string | null, pct: i.pct as string | null })));
  const indices: IndexRow[] = liveIdx.map((i) => ({ ...i, ltp: i.ltp ?? "", change: i.change ?? "", pct: i.pct ?? "", trend: trendLabel(Number(i.pct)) }));
  const chartIndex = indices.find((i) => i.key === chartKey) ?? indices[0];
  const livePopular = useLiveRows(popular.data?.items ?? []);
  let rows = livePopular.filter((r) => r.ltp !== null);
  if (view !== "popular") {
    rows = [...rows].sort((a, b) => Number(b.pct) - Number(a.pct));
    if (view === "losers") rows.reverse();
    rows = rows.filter((r) => (view === "gainers" ? Number(r.pct) > 0 : Number(r.pct) < 0));
  }

  return (
    <div className="space-y-5">
      <section>
        <h2 className="font-semibold mb-2">Indices</h2>
        {overview.error && !overview.data ? <ErrorNote text={overview.error} /> : (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {indices.map((i) => <IndexCard key={i.key} i={i} active={i.key === chartIndex?.key} onClick={() => setChartKey(i.key)} />)}
            {!overview.data && <div className="text-sm text-muted py-4">Loading…</div>}
          </div>
        )}
        {overview.data && !overview.data.market_open && (
          <div className="text-xs text-muted mt-2">Market is closed. Prices show the last close and the change versus the previous close.</div>
        )}
      </section>

      {chartIndex && (
        <section className="panel p-4">
          <ChartView symbol={chartIndex.key} exchange={chartIndex.exchange} title={chartIndex.name} height={340} />
        </section>
      )}

      {indices.length > 0 && (
        <section>
          <h2 className="font-semibold mb-1">Live Market Trends</h2>
          <div className="text-xs text-muted mb-2">Based on today&apos;s change versus the previous close. Moves with the live price.</div>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
            {indices.map((i) => <TrendTile key={i.key} i={i} />)}
          </div>
        </section>
      )}

      <section>
        <h2 className="font-semibold mb-2">Positions &amp; Orders</h2>
        <div className="grid sm:grid-cols-3 gap-3">
          <Link to="/positions" className="panel p-4 hover:bg-soft">
            <div className="text-sm text-muted">Positions</div>
            <div className="text-lg font-semibold mt-1">{dash?.stats.open_positions ?? 0} open</div>
            {dash && dash.stats.open_positions > 0 && (
              <div className={`text-sm ${pnlClass(kpi?.unrealized ?? dash.pnl.unrealized)}`}>{inr(kpi?.unrealized ?? dash.pnl.unrealized, true)} unrealized</div>
            )}
          </Link>
          <Link to="/order-book" className="panel p-4 hover:bg-soft">
            <div className="text-sm text-muted">Orders</div>
            <div className="text-lg font-semibold mt-1">{dash?.orders_today ?? 0} today</div>
          </Link>
          <Link to="/trade-book" className="panel p-4 hover:bg-soft">
            <div className="text-sm text-muted">Completed trades</div>
            <div className="text-lg font-semibold mt-1">{dash?.stats.total_trades ?? 0}</div>
            {dash && dash.stats.win_rate !== null && <div className="text-sm text-muted">Win rate {dash.stats.win_rate.toFixed(0)}%</div>}
          </Link>
        </div>
      </section>

      <section className="panel p-4">
        <div className="flex gap-2 mb-2">
          {(["popular", "gainers", "losers"] as const).map((v) => (
            <button key={v} className={view === v ? "chip-on" : "chip"} onClick={() => setView(v)}>
              {v === "popular" ? "Popular stocks" : v === "gainers" ? "Gainers" : "Losers"}
            </button>
          ))}
        </div>
        {popular.error && !popular.data ? <ErrorNote text={popular.error} /> : rows.length === 0 ? (
          <div className="text-sm text-muted py-6 text-center">{popular.data ? "Nothing to show right now." : "Loading…"}</div>
        ) : rows.map((r) => <StockRow key={r.symbol} r={r} />)}
        <div className="text-xs text-muted mt-2">Gainers and losers are ranked among this popular list only, not the whole market.</div>
      </section>
    </div>
  );
}

function ContractList({ title, items, note }: { title: string; items: ContractQuote[]; note?: string }) {
  return (
    <section className="panel p-4">
      <h2 className="font-semibold mb-1">{title}</h2>
      {items.map((r) => <ContractRow key={r.contract} r={r} />)}
      {note && <div className="text-xs text-muted mt-2">{note}</div>}
    </section>
  );
}

function CommoditiesTab() {
  const raw = usePolled<{ items: ContractQuote[]; market_open: boolean }>("/api/market/commodities", 15000);
  const items = useLiveRows(raw.data?.items ?? []);
  const d = { data: raw.data ? { ...raw.data, items } : null, error: raw.error };
  if (d.error && !d.data) return <ErrorNote text={d.error} />;
  if (!d.data) return <div className="text-sm text-muted py-6">Loading…</div>;
  return (
    <div className="max-w-3xl space-y-2">
      <div className="text-xs text-muted">MCX · {d.data.market_open ? "market open (09:00–23:30)" : "market closed (opens 09:00 on weekdays)"}</div>
      <ContractList title="Commodity futures" items={d.data.items}
                    note="Nearest-expiry contract of each commodity. Gold is quoted per 10 g, so its quantity is in units of 10 g (1 lot of GOLD = 100 units). Margin is an approximate fixed percentage." />
    </div>
  );
}

function FnoTab() {
  const raw = usePolled<{ indices: ContractQuote[]; stocks: ContractQuote[]; market_open: boolean }>("/api/market/fno", 15000);
  const indices = useLiveRows(raw.data?.indices ?? []);
  const stocks = useLiveRows(raw.data?.stocks ?? []);
  const d = { data: raw.data ? { ...raw.data, indices, stocks } : null, error: raw.error };
  if (d.error && !d.data) return <ErrorNote text={d.error} />;
  if (!d.data) return <div className="text-sm text-muted py-6">Loading…</div>;
  return (
    <div className="grid lg:grid-cols-2 gap-4 max-w-5xl">
      <ContractList title="Index futures" items={d.data.indices} note="Open an index to trade its futures or options chain." />
      <ContractList title="Stock futures" items={d.data.stocks} />
    </div>
  );
}

function EtfsTab() {
  const etfsRaw = usePolled<{ items: QuoteRow[] }>("/api/market/lists/etfs", 15000);
  const liveEtfs = useLiveRows(etfsRaw.data?.items ?? []);
  const etfs = { data: etfsRaw.data ? { items: liveEtfs } : null, error: etfsRaw.error };
  return (
    <section className="panel p-4">
      <h2 className="font-semibold mb-1">Popular ETFs</h2>
      {etfs.error && !etfs.data ? <ErrorNote text={etfs.error} /> : (etfs.data?.items ?? []).map((r) => <StockRow key={r.symbol} r={r} />)}
      {!etfs.data && !etfs.error && <div className="text-sm text-muted py-6">Loading…</div>}
    </section>
  );
}

export default function HomePage() {
  const { accountId, accounts } = useAuth();
  const [tab, setTab] = useState<Tab>("Stocks");
  const [dash, setDash] = useState<Dashboard | null>(null);

  const load = useCallback(() => {
    if (!accountId) return;
    api<Dashboard>(`/api/accounts/${accountId}/dashboard`).then(setDash).catch(() => {});
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);   // a fill / stop / target / square-off: refresh the KPI numbers now
  // the KPI cards follow the live price of the open positions
  const posKeys = useMemo(() => (dash?.open_positions ?? []).map(keyOfPosition).filter(Boolean), [dash]);
  const ltps = useLiveLtps(posKeys);
  const kpi = dash ? liveKpis(dash, ltps) : null;

  if (accounts.length === 0) {
    return (
      <div className="space-y-3">
        <h1 className="text-lg font-semibold">Welcome to SAHI Trading</h1>
        <p className="text-sm text-muted">Create your first virtual portfolio to start paper trading.</p>
        <CreateAccount />
      </div>
    );
  }
  return (
    <div className="space-y-5 max-w-6xl">
      {dash && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Virtual capital" value={inr(kpi!.totalCapital)} />
          <Stat label="Available balance" value={inr(kpi!.available)} />
          <Stat label="Invested" value={inr(kpi!.invested)} />
          <Stat label={`Total P&L${kpi!.allLive && dash.open_positions.length ? " ● live" : ""}`} value={inr(kpi!.total, true)} cls={pnlClass(kpi!.total)} />
        </div>
      )}
      <div className="flex gap-6 border-b border-line overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={`pb-2.5 text-[15px] whitespace-nowrap border-b-2 -mb-px ${
                    tab === t ? "border-slate-900 font-semibold text-slate-900" : "border-transparent text-muted hover:text-slate-900"}`}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Stocks" && <StocksTab dash={dash} kpi={kpi} />}
      {tab === "ETFs" && <EtfsTab />}
      {tab === "F&O" && <FnoTab />}
      {tab === "Commodities" && <CommoditiesTab />}
      {UNSUPPORTED[tab] && <div className="panel p-6 text-sm text-muted max-w-xl">{UNSUPPORTED[tab]}</div>}
    </div>
  );
}
