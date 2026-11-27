import { Columns2, List, MoreVertical, Plus, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChartArt } from "../components/art";
import { type QuoteRow } from "../components/market";
import { openSearch } from "../components/search";
import { Chip, EmptyState, Flash, PageTitle, PriceCell, Segmented, Skeleton, Tabs } from "../components/ui";
import { api } from "../services/api";
import { changeText, pnlClass, price } from "../utils/format";
import { useLiveRows } from "../utils/liveSocket";
import { displayName, readRecent } from "../utils/names";

interface Item extends QuoteRow { token?: string }
interface WList { id: number; name: string; prices_available: boolean; items: Item[] }
type Mode = "lists" | "recent";
type Layout = "list" | "grid";
const LAYOUT_KEY = "sahi_wl_layout";

function Rows({ items, layout, edit, onRemove }: { items: Item[]; layout: Layout; edit: boolean; onRemove?: (i: Item) => void }) {
  const live = useLiveRows(items);
  if (layout === "grid") {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 py-4">
        {live.map((i) => (
          <div key={i.instrument_id} className="card relative px-4 py-4">
            <Link to={`/trade?symbol=${i.symbol}&exchange=${i.exchange}`} className="block active:opacity-60">
              <div className="text-[15px] lg:text-[16px] truncate pr-5">{displayName(i.symbol)}</div>
              <div className="text-[12px] lg:text-[13px] text-muted">{i.exchange}</div>
              <div className="mt-3 text-[16.5px] lg:text-[19px] font-medium"><Flash value={i.ltp}>{price(i.ltp)}</Flash></div>
              <div className={`text-[13px] lg:text-[14px] ${i.change ? pnlClass(i.change) : "text-muted"}`}>{changeText(i.change, i.pct)}</div>
            </Link>
            {edit && onRemove && <button aria-label={`Remove ${i.symbol}`} onClick={() => onRemove(i)} className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full bg-panel2"><X size={15} /></button>}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div>
      {live.map((i) => (
        <div key={i.instrument_id} className="row">
          {edit && onRemove && <button aria-label={`Remove ${i.symbol}`} onClick={() => onRemove(i)} className="h-8 w-8 shrink-0 grid place-items-center rounded-full bg-sellbg text-sell animate-fade"><Trash2 size={15} /></button>}
          <Link to={`/trade?symbol=${i.symbol}&exchange=${i.exchange}`} className="flex-1 min-w-0 active:opacity-60">
            <div className="row-name">{displayName(i.symbol)}</div>
            <div className="row-sub">{i.exchange}</div>
          </Link>
          <PriceCell ltp={i.ltp} change={i.change} pct={i.pct} />
        </div>
      ))}
    </div>
  );
}

function RecentList({ layout }: { layout: Layout }) {
  const recent = useMemo(() => readRecent().filter((r) => r.exchange === "NSE"), []);
  const [rows, setRows] = useState<Record<string, Item>>({});
  useEffect(() => {
    recent.forEach((r) => api<Item>(`/api/market/quote/${r.symbol}?exchange=NSE`).then((q) => setRows((c) => ({ ...c, [r.symbol]: q }))).catch(() => {}));
  }, [recent]);
  const items = recent.map((r) => rows[r.symbol]).filter(Boolean) as Item[];
  if (!recent.length) return <EmptyState art={<ChartArt />} title="Nothing viewed yet" text="Stocks you open appear here." />;
  return <div className="px-4 lg:px-0"><Rows items={items} layout={layout} edit={false} /></div>;
}

export default function WatchlistPage() {
  const [lists, setLists] = useState<WList[] | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<Mode>("lists");
  const [layout, setLayoutState] = useState<Layout>(() => { try { return (localStorage.getItem(LAYOUT_KEY) as Layout) || "list"; } catch { return "list"; } });
  const setLayout = (l: Layout) => { setLayoutState(l); try { localStorage.setItem(LAYOUT_KEY, l); } catch { /* ignore */ } };
  const [edit, setEdit] = useState(false);
  const [menu, setMenu] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api<WList[]>("/api/watchlists").then((l) => {
      setLists(l);
      setActiveId((cur) => (cur && l.some((x) => x.id === cur) ? cur : l[0]?.id ?? null));
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    try { await fn(); load(); } catch (e) { setError((e as Error).message); }
  };
  const active = lists?.find((l) => l.id === activeId);
  const create = () => {
    if (!newName.trim()) return;
    run(async () => {
      const w = await api<WList>("/api/watchlists", { method: "POST", json: { name: newName.trim() } });
      setActiveId(w.id); setNewName(""); setCreating(false);
    });
  };
  const addStock = () => openSearch({
    placeholder: `Search & add to ${active?.name ?? "watchlist"}`,
    onPick: (h) => run(() => api(`/api/watchlists/${activeId}/items`, { method: "POST", json: { symbol: h.symbol, exchange: h.exchange } })),
  });

  return (
    <div className="lg:max-w-[820px]">
      <PageTitle>Watchlist</PageTitle>
      <div className="flex gap-2.5 overflow-x-auto no-scrollbar px-4 lg:px-0 pb-1">
        <Chip on={mode === "lists"} onClick={() => setMode("lists")}>My Lists</Chip>
        <Chip on={mode === "recent"} onClick={() => setMode("recent")}>Recently viewed</Chip>
      </div>

      {mode === "recent" ? (
        <><div className="px-4 lg:px-0 pt-5"><LayoutSwitch layout={layout} setLayout={setLayout} /></div><RecentList layout={layout} /></>
      ) : (
        <>
          <div className="mt-4">
            <Tabs size="lg" value={String(activeId ?? "")} onChange={(v) => { setActiveId(Number(v)); setEdit(false); }}
                  items={(lists ?? []).map((l) => ({ value: String(l.id), label: l.name }))}
                  right={
                    <div className="flex items-center gap-2 pr-3 lg:pr-0 shrink-0">
                      <div ref={menuRef} className="relative">
                        <button aria-label="List options" className="h-10 w-8 grid place-items-center" onClick={() => setMenu(!menu)}><MoreVertical size={22} /></button>
                        {menu && active && (
                          <div className="absolute right-0 top-11 z-30 w-52 card shadow-float py-1.5 animate-fade">
                            <button className="w-full text-left px-4 py-3 text-[14px] lg:text-[15px] active:bg-soft" onClick={() => { setEdit(!edit); setMenu(false); }}>{edit ? "Done editing" : "Edit stocks"}</button>
                            {lists && lists.length > 1 && (
                              <button className="w-full text-left px-4 py-3 text-[14px] lg:text-[15px] text-sell active:bg-soft"
                                      onClick={() => { setMenu(false); if (window.confirm(`Delete "${active.name}"?`)) run(() => api(`/api/watchlists/${active.id}`, { method: "DELETE" })); }}>Delete list</button>
                            )}
                          </div>
                        )}
                      </div>
                      <button aria-label="New list" className="icon-btn-grey" onClick={() => setCreating(!creating)}><Plus size={22} /></button>
                    </div>
                  } />
          </div>
          {creating && (
            <form onSubmit={(e) => { e.preventDefault(); create(); }} className="flex gap-2 px-4 lg:px-0 pt-4 animate-fade">
              <input autoFocus className="input !rounded-full" placeholder="New list name" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <button className="btn-primary px-6">Create</button>
            </form>
          )}
          {error && <div role="alert" className="mx-4 lg:mx-0 mt-3 rounded-2xl bg-sellbg/60 px-4 py-3 text-[14px] lg:text-[15px] text-sell">{error}</div>}
          <div className="px-4 lg:px-0 pt-5 flex items-center justify-between">
            <LayoutSwitch layout={layout} setLayout={setLayout} />
            {edit && <button className="text-[14px] lg:text-[15px] font-medium" onClick={() => setEdit(false)}>Done</button>}
          </div>
          <div className="px-4 lg:px-0">
            {lists === null ? <Skeleton rows={6} /> : !active ? null : active.items.length === 0 ? (
              <EmptyState art={<ChartArt />} title={`${active.name} is empty`} text="Search and add stocks to follow them here."
                          action={<button className="btn-pill" onClick={addStock}>Search &amp; Add</button>} />
            ) : (
              <>
                {!active.prices_available && <div className="text-[13px] lg:text-[14px] text-[#b26a00] pt-3">Prices are unavailable right now.</div>}
                <Rows items={active.items} layout={layout} edit={edit}
                      onRemove={(i) => run(() => api(`/api/watchlists/${active.id}/items/${i.instrument_id}`, { method: "DELETE" }))} />
              </>
            )}
          </div>
          <div className="h-20" />
          {/* floating search & add pill */}
          <div className="fixed left-1/2 -translate-x-1/2 bottom-[calc(76px+env(safe-area-inset-bottom))] lg:bottom-8 lg:left-[calc(50%+124px)] z-30">
            <div className="flex items-center gap-1 rounded-full bg-white/95 backdrop-blur shadow-float border border-line pl-2 pr-1.5 py-1.5">
              <button aria-label="Edit list" onClick={() => setEdit(!edit)} className={`h-11 w-11 grid place-items-center rounded-full ${edit ? "bg-ink text-white" : ""}`}><Trash2 size={19} strokeWidth={1.7} /></button>
              <span className="w-px h-6 bg-line" />
              <button onClick={addStock} className="h-11 flex items-center gap-2 rounded-full bg-panel2 px-5 text-[15px] lg:text-[16px] text-[#444] whitespace-nowrap press"><Search size={19} />Search &amp; Add</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function LayoutSwitch({ layout, setLayout }: { layout: Layout; setLayout: (l: Layout) => void }) {
  return (
    <Segmented tone="light" size="sm" value={layout} onChange={setLayout}
               items={[["list", <List key="l" size={20} aria-label="List view" />], ["grid", <Columns2 key="g" size={20} aria-label="Column view" />]]} />
  );
}
