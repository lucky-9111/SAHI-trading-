/** Full-screen search (phone) / centred search panel (desktop). Opened from anywhere with openSearch(). */
import { ChevronLeft, Clock, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { displayName, readRecent } from "../utils/names";

export interface InstrumentHit { id: number; symbol: string; name: string | null; exchange: string; instrument_type: string }
interface Opts { onPick?: (h: InstrumentHit) => void; placeholder?: string }

let listener: ((o: Opts | null) => void) | null = null;
export function openSearch(opts: Opts = {}): void { listener?.(opts); }

const TYPE: Record<string, string> = { EQ: "Stock", IDX: "Index", COM: "Commodity", FUT: "Futures", OPT: "Option" };

export default function SearchOverlay() {
  const nav = useNavigate();
  const [opts, setOpts] = useState<Opts | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { listener = (o) => { setOpts(o); setQ(""); setHits([]); }; return () => { listener = null; }; }, []);
  useEffect(() => { if (opts) setTimeout(() => input.current?.focus(), 60); }, [opts]);
  useEffect(() => {
    if (!opts) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpts(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [opts]);
  useEffect(() => {
    const term = q.trim();
    if (!term) { setHits([]); return; }
    setBusy(true);
    const t = setTimeout(() => {
      api<InstrumentHit[]>(`/api/instruments/search?q=${encodeURIComponent(term)}&limit=15`)
        .then(setHits).catch(() => setHits([])).finally(() => setBusy(false));
    }, 140);
    return () => clearTimeout(t);
  }, [q]);

  if (!opts) return null;
  const pick = (h: InstrumentHit) => {
    const o = opts;
    setOpts(null);
    if (o.onPick) o.onPick(h);
    else nav(`/trade?symbol=${encodeURIComponent(h.symbol)}&exchange=${h.exchange}`);
  };
  const recent = readRecent();
  return (
    <div className="fixed inset-0 z-50 bg-white lg:bg-black/40 lg:grid lg:place-items-start lg:pt-24 animate-backdrop" onClick={() => setOpts(null)}>
      <div className="h-full lg:h-auto lg:max-h-[70vh] lg:w-[620px] lg:mx-auto bg-white lg:rounded-[24px] lg:shadow-float flex flex-col overflow-hidden animate-fade"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-3 pt-safe h-[68px] border-b border-line">
          <button aria-label="Close search" className="h-10 w-10 grid place-items-center rounded-full active:bg-soft lg:hidden" onClick={() => setOpts(null)}>
            <ChevronLeft size={28} strokeWidth={1.8} />
          </button>
          <Search size={20} className="text-muted hidden lg:block ml-2" />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search"
                 onKeyDown={(e) => e.key === "Enter" && hits[0] && pick(hits[0])}
                 placeholder={opts.placeholder ?? "Search stocks, indices, commodities"}
                 className="flex-1 h-11 text-[17px] outline-none placeholder:text-faint bg-transparent" />
          {q && <button aria-label="Clear" className="h-9 w-9 grid place-items-center rounded-full bg-panel2" onClick={() => setQ("")}><X size={16} /></button>}
        </div>
        <div className="flex-1 overflow-y-auto px-4">
          {!q.trim() && recent.length > 0 && (
            <>
              <div className="pt-5 pb-2 text-[13px] uppercase tracking-wide text-muted">Recently viewed</div>
              {recent.slice(0, 8).map((r) => (
                <button key={r.symbol + r.exchange} className="w-full row text-left active:bg-soft"
                        onClick={() => pick({ id: 0, symbol: r.symbol, exchange: r.exchange, name: null, instrument_type: "" })}>
                  <div className="flex items-center gap-3 min-w-0"><Clock size={18} className="text-faint shrink-0" />
                    <div className="min-w-0"><div className="row-name">{displayName(r.symbol)}</div><div className="row-sub">{r.exchange}</div></div></div>
                </button>
              ))}
            </>
          )}
          {hits.map((h) => (
            <button key={`${h.exchange}${h.symbol}${h.id}`} className="w-full row text-left active:bg-soft" onClick={() => pick(h)}>
              <div className="min-w-0">
                <div className="row-name">{displayName(h.symbol)}</div>
                <div className="row-sub">{h.symbol !== displayName(h.symbol) ? `${h.symbol} · ` : ""}{h.exchange}</div>
              </div>
              <span className="text-[13px] text-muted rounded-full bg-soft px-3 py-1">{TYPE[h.instrument_type] ?? h.instrument_type}</span>
            </button>
          ))}
          {q.trim() && !busy && hits.length === 0 && <div className="py-10 text-center text-muted">No match for “{q}”.</div>}
        </div>
      </div>
    </div>
  );
}
