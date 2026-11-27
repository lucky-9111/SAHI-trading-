import {
  CandlestickSeries, ColorType, createChart, HistogramSeries, LineSeries,
  type IChartApi, type IPriceLine, type ISeriesApi, type LogicalRange, type UTCTimestamp,
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

const IST_SHIFT = 19800; // candle times are IST wall-clock treated as UTC

export default function CandleChart({ candles, ma, height = 520, lines = [], showBB = false, showRSI = false, live = null, tfSeconds }: {
  candles: Candle[]; ma: { period: number; color: string }[]; height?: number; lines?: PriceLine[];
  showBB?: boolean; showRSI?: boolean;
  /** latest pushed price: moves the last candle (or opens the next one on an intraday timeframe) */
  live?: number | null; tfSeconds?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastRef = useRef<Candle | null>(null);
  // The user's zoom/scroll survives rebuilds (indicator toggles). Only new candles (symbol/timeframe) re-fit the view.
  const viewRef = useRef<{ candles: Candle[]; range: LogicalRange | null } | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const linesRef = useRef(lines);
  linesRef.current = lines;
  // Parents often pass a new array with the same levels (e.g. positions polled every 10 s): compare by value.
  const linesKey = JSON.stringify(lines);

  const applyLines = (series: ISeriesApi<"Candlestick">, list: PriceLine[]) => {
    priceLinesRef.current.forEach((pl) => series.removePriceLine(pl));
    // Your own entry / stop-loss / target levels (with the strategy name on the entry line)
    priceLinesRef.current = list.map((l) => series.createPriceLine({
      price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? 2 : 0, axisLabelVisible: true, title: l.title,
    }));
  };

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
    seriesRef.current = series;
    lastRef.current = candles.length ? { ...candles[candles.length - 1] } : null;
    priceLinesRef.current = [];
    applyLines(series, linesRef.current);

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
      // reference levels: 60 = bullish zone, 50 = midline, 40 = bearish zone
      [{ price: 60, color: "#0b9d6c" }, { price: 50, color: "#94a3b8" }, { price: 40, color: "#d93636" }].forEach((l) =>
        pane.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" }));
    }
    const prev = viewRef.current;
    if (prev && prev.candles === candles && prev.range) chart.timeScale().setVisibleLogicalRange(prev.range);
    else chart.timeScale().fitContent();
    return () => {
      viewRef.current = { candles, range: chart.timeScale().getVisibleLogicalRange() };
      chart.remove(); chartRef.current = null; seriesRef.current = null; priceLinesRef.current = [];
    };
  }, [candles, ma, showBB, showRSI]);  // eslint-disable-line react-hooks/exhaustive-deps

  // entry / SL / target lines change in place: no rebuild, zoom untouched
  useEffect(() => {
    if (seriesRef.current) applyLines(seriesRef.current, linesRef.current);
  }, [linesKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  // live price: update the last candle in place; on intraday timeframes open the next candle when its time has come (keeps the broker's alignment)
  useEffect(() => {
    const s = seriesRef.current, last = lastRef.current;
    if (!s || !last || live == null) return;
    const nowIst = Math.floor(Date.now() / 1000) + IST_SHIFT;
    let bar: Candle;
    if (tfSeconds && nowIst >= last.time + tfSeconds) {
      const k = Math.floor((nowIst - last.time) / tfSeconds);
      bar = { time: last.time + k * tfSeconds, open: live, high: live, low: live, close: live, volume: 0 };
    } else {
      bar = { ...last, high: Math.max(last.high, live), low: Math.min(last.low, live), close: live };
    }
    lastRef.current = bar;
    s.update({ time: bar.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
  }, [live, tfSeconds]);

  return <div ref={el} className="w-full" style={{ height }} />;
}
