import {
  CandlestickSeries, ColorType, createChart, HistogramSeries, LineSeries, type IChartApi, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { bollinger, rsi } from "../utils/indicators";

export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number }

/** Simple moving average of closes (display indicator computed from real candles). */
export function sma(candles: Candle[], period: number): { time: UTCTimestamp; value: number }[] {
  const out: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  candles.forEach((c, i) => {
    sum += c.close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) out.push({ time: c.time as UTCTimestamp, value: sum / period });
  });
  return out;
}

export interface PriceLine { price: number; color: string; title: string; dashed?: boolean }

export default function CandleChart({ candles, ma, height = 520, lines = [], showBB = false, showRSI = false }: {
  candles: Candle[]; ma: { period: number; color: string }[]; height?: number; lines?: PriceLine[];
  showBB?: boolean; showRSI?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#6b7280" },
      grid: { vertLines: { color: "#f1f3f5" }, horzLines: { color: "#f1f3f5" } },
      rightPriceScale: { borderColor: "#e6e8eb" },
      timeScale: { borderColor: "#e6e8eb", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#0b9d6c", downColor: "#d93636", borderUpColor: "#0b9d6c", borderDownColor: "#d93636",
      wickUpColor: "#0b9d6c", wickDownColor: "#d93636",
    });
    series.setData(candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    // Your own entry / stop-loss / target levels (with the strategy name on the entry line)
    lines.forEach((l) => series.createPriceLine({
      price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? 2 : 0, axisLabelVisible: true, title: l.title,
    }));

    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(candles.map((c) => ({
      time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? "#0b9d6c55" : "#d9363655",
    })));

    ma.forEach(({ period, color }) => {
      chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        .setData(sma(candles, period));
    });
    if (showBB) {
      const bb = bollinger(candles.map((c) => c.close));
      (["upper", "mid", "lower"] as const).forEach((k) => {
        const data = candles.flatMap((c, i) => (bb[i] ? [{ time: c.time as UTCTimestamp, value: bb[i]![k] }] : []));
        chart.addSeries(LineSeries, { color: k === "mid" ? "#94a3b8" : "#06b6d4", lineWidth: 1, lineStyle: k === "mid" ? 2 : 0,
          priceLineVisible: false, lastValueVisible: false }).setData(data);
      });
    }
    if (showRSI) {
      const r = rsi(candles.map((c) => c.close));
      const pane = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, title: "RSI 14" }, 1);
      pane.setData(candles.flatMap((c, i) => (r[i] != null ? [{ time: c.time as UTCTimestamp, value: r[i]! }] : [])));
      pane.createPriceLine({ price: 70, color: "#d93636", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      pane.createPriceLine({ price: 30, color: "#0b9d6c", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    }
    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [candles, ma, lines, showBB, showRSI]);

  return <div ref={el} className="w-full" style={{ height }} />;
}
