import { Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { InstrumentHit } from "../components/StockSearch";
import { api } from "../services/api";
import { changeText, pnlClass, price } from "../utils/format";

interface Item {
  instrument_id: number; symbol: string; exchange: string;
  ltp: string | null; change: string | null; pct: string | null; volume: number | null;
}
interface WList { id: number; name: string; prices_available: boolean; items: Item[] }

export default function WatchlistPage() {
  const [lists, setLists] = useState<WList[] | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);

  const load = useCallback(() => {
    api<WList[]>("/api/watchlists").then((l) => {
      setLists(l);
      setActiveId((cur) => (cur && l.some((x) => x.id === cur) ? cur : l[0]?.id ?? null));
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    const t = setTimeout(() => {
      api<InstrumentHit[]>(`/api/instruments/search?q=${encodeURIComponent(term)}&limit=6`).then(setHits).catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    try { await fn(); load(); } catch (e) { setError((e as Error).message); }
  };
  const active = lists?.find((l) => l.id === activeId);
  const create = (e: FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    run(async () => {
      const w = await api<WList>("/api/watchlists", { method: "POST", json: { name: newName.trim() } });
      setActiveId(w.id); setNewName("");
    });
  };
  const add = (h: InstrumentHit) => run(async () => {
    await api(`/api/watchlists/${activeId}/items`, { method: "POST", json: { symbol: h.symbol, exchange: h.exchange } });
    setQ(""); setHits([]);
  });

  return (
    <div className="space-y-4 max-w-4xl">
      <h1 className="text-lg font-semibold">Watchlist</h1>
      <div className="flex flex-wrap items-center gap-2">
        {lists?.map((l) => (
          <button key={l.id} className={l.id === activeId ? "chip-on" : "chip"} onClick={() => setActiveId(l.id)}>{l.name}</button>
        ))}
        <form onSubmit={create} className="flex items-center gap-1">
          <input className="input !w-36 !rounded-full !py-1.5" placeholder="New list" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button className="btn-ghost !px-2.5 !py-1.5" aria-label="Create watchlist"><Plus size={16} /></button>
        </form>
      </div>
      {error && <div role="alert" className="text-sm text-down">{error}</div>}

      {active && (
        <div className="panel p-4">
          <div className="flex items-center justify-between mb-3 gap-3">
            <div className="relative flex-1 max-w-sm">
              <input className="input" placeholder={`Add a stock to ${active.name}…`} value={q} onChange={(e) => setQ(e.target.value)} />
              {hits.length > 0 && (
                <ul className="absolute z-30 mt-1 w-full panel max-h-64 overflow-y-auto">
                  {hits.map((h) => (
                    <li key={h.id}><button className="w-full flex justify-between px-3 py-2 text-sm hover:bg-panel2" onClick={() => add(h)}>
                      <span className="font-medium">{h.symbol}</span><span className="text-xs text-muted">{h.exchange}</span></button></li>
                  ))}
                </ul>
              )}
            </div>
            {lists && lists.length > 1 && (
              <button className="btn-ghost text-down" onClick={() => window.confirm(`Delete "${active.name}"?`) && run(() => api(`/api/watchlists/${active.id}`, { method: "DELETE" }))}>
                <Trash2 size={15} /> Delete list
              </button>
            )}
          </div>
          {!active.prices_available && active.items.length > 0 && (
            <div className="text-xs text-amber-600 mb-2">Prices are unavailable right now (market data not connected).</div>
          )}
          {active.items.length === 0 ? (
            <div className="text-sm text-muted py-8 text-center">This watchlist is empty. Search above to add stocks.</div>
          ) : (
            <table className="w-full">
              <thead><tr className="border-b border-line">
                <th className="th">Stock</th><th className="th text-right">LTP</th><th className="th text-right">Change</th>
                <th className="th text-right">Volume</th><th className="th" /></tr></thead>
              <tbody>
                {active.items.map((i) => (
                  <tr key={i.instrument_id} className="border-b border-line last:border-0">
                    <td className="td"><Link className="font-medium hover:underline" to={`/trade?symbol=${i.symbol}&exchange=${i.exchange}`}>{i.symbol}</Link>
                      <div className="text-xs text-muted">{i.exchange}</div></td>
                    <td className="td text-right font-medium">{price(i.ltp)}</td>
                    <td className={`td text-right ${i.change ? pnlClass(i.change) : ""}`}>{changeText(i.change, i.pct)}</td>
                    <td className="td text-right text-muted">{i.volume ? new Intl.NumberFormat("en-IN").format(i.volume) : "—"}</td>
                    <td className="td text-right whitespace-nowrap">
                      <Link className="btn-ghost !py-1" to={`/trade?symbol=${i.symbol}&exchange=${i.exchange}`}>Trade</Link>
                      <button aria-label={`Remove ${i.symbol}`} className="ml-1 text-muted hover:text-down p-1.5"
                              onClick={() => run(() => api(`/api/watchlists/${active.id}/items/${i.instrument_id}`, { method: "DELETE" }))}><X size={16} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
