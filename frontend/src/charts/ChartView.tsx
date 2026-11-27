import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useLiveTick } from "../utils/liveSocket";
import CandleChart, { type Candle, type PriceLine } from "./CandleChart";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"] as const;
const LABEL: Record<string, string> = { "1d": "D", "1w": "W", "1M": "M" };
const MAS = [
  { period: 20, color: "#3b82f6" },
  { period: 50, color: "#f59e0b" },
  { period: 200, color: "#a855f7" },
];

interface CandleResponse { candles: Candle[]; source: string; token?: string; exchange?: string; status: { state: string } }
const TF_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600 };

export default function ChartView({ symbol, exchange, height = 520, title, lines }: {
  symbol: string; exchange: string; height?: number; title?: string; lines?: PriceLine[];
}) {
  const [tf, setTf] = useState<string>("15m");
  const [maOn, setMaOn] = useState<Record<number, boolean>>({ 20: true, 50: true, 200: false });
  const [showBB, setShowBB] = useState(false);
  const [showRSI, setShowRSI] = useState(false);
  const [data, setData] = useState<CandleResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let stale = false;
    setLoading(true); setError(""); setData(null);
    api<CandleResponse>(`/api/market/candles?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}&timeframe=${tf}`)
      .then((r) => { if (!stale) setData(r); })
      .catch((e) => { if (!stale) setError(e.message); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [symbol, exchange, tf]);

  const activeMas = useMemo(() => MAS.filter((m) => maOn[m.period]), [maOn]);
  const last = data?.candles.at(-1);
  const { tick, fresh, feed } = useLiveTick(data?.exchange, data?.token);
  const liveText = fresh ? "LIVE" : feed === "reconnecting" || feed === "offline" ? "Reconnecting…" : feed === "stale" ? "Feed stale" : feed === "closed" ? "Market closed" : tick ? "Quiet (no recent trade)" : "Waiting for ticks…";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">{title ?? symbol} <span className="text-sm text-muted">{exchange}</span></h2>
        {last && <span className="text-sm">{fresh ? "LTP" : "Last close"} <b>{(fresh && tick ? tick.ltp : last.close).toFixed(2)}</b></span>}
        {data && <span className={`text-xs font-medium ${fresh ? "text-up" : "text-muted"}`} title="Prices pushed by Angel One over a websocket">● {liveText}</span>}
        <div className="flex-1" />
        <div className="flex gap-1">
          {TIMEFRAMES.map((t) => (
            <button key={t} onClick={() => setTf(t)}
                    className={`px-3 py-1 rounded-full text-sm ${tf === t ? "bg-accent text-white" : "text-slate-600 hover:bg-panel2"}`}>
              {LABEL[t] ?? t}
            </button>
          ))}
        </div>
        <div className="flex gap-3 text-sm">
          {MAS.map((m) => (
            <label key={m.period} className="flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={!!maOn[m.period]}
                     onChange={(e) => setMaOn({ ...maOn, [m.period]: e.target.checked })} />
              <span style={{ color: m.color }}>MA{m.period}</span>
            </label>
          ))}
          <label className="flex items-center gap-1 cursor-pointer"><input type="checkbox" checked={showBB} onChange={(e) => setShowBB(e.target.checked)} /><span style={{ color: "#06b6d4" }}>Bollinger</span></label>
          <label className="flex items-center gap-1 cursor-pointer"><input type="checkbox" checked={showRSI} onChange={(e) => setShowRSI(e.target.checked)} /><span style={{ color: "#8b5cf6" }}>RSI</span></label>
        </div>
      </div>
      <div className="panel overflow-hidden">
        {loading && <div className="p-6 text-sm text-muted">Loading candles…</div>}
        {error && (
          <div className="p-6 text-sm" role="alert">
            <div className="font-medium text-down">Chart unavailable</div>
            <p className="text-muted mt-1">{error}</p>
          </div>
        )}
        {data && data.candles.length > 0 && <CandleChart candles={data.candles} ma={activeMas} height={height} lines={lines} showBB={showBB} showRSI={showRSI} live={fresh && tick ? tick.ltp : null} tfSeconds={TF_SECONDS[tf]} />}
      </div>
      {data && <div className="text-xs text-muted">Source: {data.source} · {data.status.state} · Times in IST · Historical candles + live ticks</div>}
    </div>
  );
}
