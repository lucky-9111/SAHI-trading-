import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";

export interface InstrumentHit { id: number; symbol: string; name: string | null; exchange: string; instrument_type: string }
interface Status { count: number; syncing: boolean; error: string | null }

export default function StockSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [status, setStatus] = useState<Status | null>(null);
  const box = useRef<HTMLDivElement>(null);

  // Poll status while the instrument master is still loading
  useEffect(() => {
    let stop = false;
    const tick = () => api<Status>("/api/instruments/status").then((s) => {
      if (stop) return;
      setStatus(s);
      if (s.count === 0 && !s.error) setTimeout(tick, 3000);
    }).catch(() => {});
    tick();
    return () => { stop = true; };
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    const t = setTimeout(() => {
      api<InstrumentHit[]>(`/api/instruments/search?q=${encodeURIComponent(term)}&limit=10`)
        .then((r) => { setHits(r); setActive(0); }).catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const pick = (h: InstrumentHit) => {
    setOpen(false); setQ("");
    nav(`/trade?symbol=${encodeURIComponent(h.symbol)}&exchange=${h.exchange}`);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && hits[active]) pick(hits[active]);
    else if (e.key === "Escape") setOpen(false);
  };

  const loading = status !== null && status.count === 0;
  return (
    <div ref={box} className="relative flex-1 max-w-xl">
      <Search size={16} className="absolute left-3 top-2.5 text-muted" />
      <input className="input pl-9" value={q} onKeyDown={onKey} aria-label="Search stocks"
             placeholder={loading ? "Loading NSE stock list…" : "Search stocks… (e.g. RELIANCE, TCS)"}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} />
      {open && q.trim() && (
        <ul className="absolute z-40 mt-1 w-full panel max-h-80 overflow-y-auto shadow-xl">
          {hits.map((h, i) => (
            <li key={h.id}>
              <button className={`w-full flex justify-between px-3 py-2 text-sm text-left ${i === active ? "bg-panel2" : ""}`}
                      onMouseEnter={() => setActive(i)} onClick={() => pick(h)}>
                <span className="font-medium">{h.symbol}</span>
                <span className="text-xs text-muted">{h.exchange} · {h.instrument_type}</span>
              </button>
            </li>
          ))}
          {hits.length === 0 && (
            <li className="px-3 py-3 text-sm text-muted">
              {loading ? "Stock list is still downloading, try again in a moment."
                : status?.error ? `Stock list failed to load: ${status.error}` : "No matching stock."}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
