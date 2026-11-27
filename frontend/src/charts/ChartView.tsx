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
    <div className="space-y-3">
      <div className="flex items-center gap-3 px-4 lg:px-0">
        {title && <h2 className="text-[16px] lg:text-[18px] font-medium">{title} <span className="text-[13px] lg:text-[14px] text-muted">{exchange}</span></h2>}
        {last && <span className="text-[14px] lg:text-[15px]">{fresh ? "LTP" : "Last close"} <b className="font-medium">{(fresh && tick ? tick.ltp : last.close).toFixed(2)}</b></span>}
        {data && <span className={`inline-flex items-center gap-1.5 text-[12px] lg:text-[13px] ${fresh ? "text-up" : "text-muted"}`} title="Prices pushed by Angel One over a websocket">
          <span className={`h-2 w-2 rounded-full ${fresh ? "bg-up animate-pulse" : "bg-faint"}`} />{liveText}</span>}
      </div>
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar px-4 lg:px-0">
        <div className="seg shrink-0">
          {TIMEFRAMES.map((t) => (
            <button key={t} onClick={() => setTf(t)}
                    className={`relative z-10 rounded-full px-3 py-[5px] lg:px-3.5 lg:py-1.5 text-[13px] lg:text-[14px] transition-colors ${tf === t ? "bg-white text-ink font-medium shadow-[0_1px_2px_rgba(0,0,0,.08)]" : "text-[#555]"}`}>
              {LABEL[t] ?? t}
            </button>
          ))}
        </div>
        {MAS.map((m) => (
          <button key={m.period} onClick={() => setMaOn({ ...maOn, [m.period]: !maOn[m.period] })}
                  className={`shrink-0 rounded-full border px-3 py-[5px] lg:px-3.5 lg:py-1.5 text-[13px] lg:text-[14px] transition-colors ${maOn[m.period] ? "border-ink" : "border-line text-muted"}`}>
            <span style={{ color: maOn[m.period] ? m.color : undefined }}>●</span> MA{m.period}
          </button>
        ))}
        <button onClick={() => setShowBB(!showBB)} className={`shrink-0 rounded-full border px-3 py-[5px] lg:px-3.5 lg:py-1.5 text-[13px] lg:text-[14px] ${showBB ? "border-ink" : "border-line text-muted"}`}><span style={{ color: showBB ? "#06b6d4" : undefined }}>●</span> Bollinger</button>
        <button onClick={() => setShowRSI(!showRSI)} className={`shrink-0 rounded-full border px-3 py-[5px] lg:px-3.5 lg:py-1.5 text-[13px] lg:text-[14px] ${showRSI ? "border-ink" : "border-line text-muted"}`}><span style={{ color: showRSI ? "#8b5cf6" : undefined }}>●</span> RSI</button>
      </div>
      <div className="overflow-hidden lg:rounded-2xl">
        {loading && <div className="skeleton mx-4 lg:mx-0" style={{ height }} />}
        {error && (
          <div className="p-6 text-sm" role="alert">
            <div className="font-medium text-down">Chart unavailable</div>
            <p className="text-muted mt-1">{error}</p>
          </div>
        )}
        {data && data.candles.length > 0 && <CandleChart candles={data.candles} ma={activeMas} height={height} lines={lines} showBB={showBB} showRSI={showRSI} live={fresh && tick ? tick.ltp : null} tfSeconds={TF_SECONDS[tf]} />}
      </div>
      {data && <div className="text-[11.5px] lg:text-[12px] text-faint px-4 lg:px-0">Source: {data.source} · {data.status.state} · Times in IST · Historical candles + live ticks</div>}
    </div>
  );
}
