import { AreaSeries, ColorType, createChart, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { useLiveTick } from "../utils/liveSocket";
import type { Candle } from "./CandleChart";

interface CandleResponse { candles: Candle[]; token?: string; exchange?: string }

/** Today's intraday price as a soft area chart (red when the day is down, green when up), moved live by pushed ticks. */
export default function AreaChart({ symbol, exchange, height = 380, prevClose }: { symbol: string; exchange: string; height?: number; prevClose?: number | null }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);
  const last = useRef<{ time: number; value: number } | null>(null);
  const [data, setData] = useState<CandleResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    setData(null); setError("");
    api<CandleResponse>(`/api/market/candles?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}&timeframe=1m`)
      .then((r) => { if (!stop) setData(r); }).catch((e) => !stop && setError(e.message));
    return () => { stop = true; };
  }, [symbol, exchange]);

  // only the latest session
  const points = (() => {
    const c = data?.candles ?? [];
    if (!c.length) return [];
    const day = Math.floor(c[c.length - 1].time / 86400);
    return c.filter((x) => Math.floor(x.time / 86400) === day).map((x) => ({ time: x.time, value: x.close }));
  })();
  const ref = prevClose ?? points[0]?.value;
  const down = points.length > 0 && ref != null && points[points.length - 1].value < ref;
  const stroke = down ? "#e0457b" : "#1a9a6b";
  const fill = down ? "rgba(224,69,123,.14)" : "rgba(26,154,107,.14)";

  useEffect(() => {
    if (!el.current || !points.length) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#777", fontFamily: "Figtree, system-ui, sans-serif", fontSize: 13 },
      grid: { vertLines: { visible: false }, horzLines: { color: "#e6e6e6", style: LineStyle.Dashed } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      handleScroll: false, handleScale: false,
    });
    const s = c.addSeries(AreaSeries, { lineColor: stroke, topColor: fill, bottomColor: "rgba(255,255,255,0)", lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    s.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    c.timeScale().fitContent();
    chart.current = c; series.current = s; last.current = points[points.length - 1];
    return () => { c.remove(); chart.current = null; series.current = null; };
  }, [data, stroke]);  // eslint-disable-line react-hooks/exhaustive-deps

  const { tick, fresh } = useLiveTick(data?.exchange, data?.token);
  useEffect(() => {
    if (!fresh || !tick || !series.current || !last.current) return;
    const nowMin = Math.floor((Date.now() / 1000 + 19800) / 60) * 60;
    const t = Math.max(nowMin, last.current.time);
    last.current = { time: t, value: tick.ltp };
    series.current.update({ time: t as UTCTimestamp, value: tick.ltp });
  }, [tick, fresh]);

  if (error) return <div className="py-16 text-center text-muted text-[14px] lg:text-[15px]">Chart unavailable: {error}</div>;
  if (!data) return <div className="skeleton w-full" style={{ height }} />;
  if (!points.length) return <div className="py-16 text-center text-muted">No intraday data yet.</div>;
  return <div ref={el} className="w-full" style={{ height }} />;
}
