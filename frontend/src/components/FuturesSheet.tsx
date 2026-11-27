import { useMemo } from "react";
import { useLiveRows } from "../utils/liveSocket";
import { pnlClass, price } from "../utils/format";
import { Sheet } from "./ui";

export interface FutureRow {
  instrument_id: number; symbol: string; exchange?: string; token?: string; expiry: string; lot_size: number;
  ltp?: string | null; prev_close?: string | null; change?: string | null; pct?: string | null; oi?: number | null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "DLF 29 Dec Fut" */
export function futureName(underlying: string, expiry: string): string {
  const [, m, d] = expiry.split("-").map(Number);
  return `${underlying} ${d} ${MONTHS[m - 1]} Fut`;
}

const signed = (v: number, digits = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}`;

/** Bottom sheet listing every live futures contract of an underlying: price, day change, open interest, premium to spot. */
export default function FuturesSheet({ open, onClose, underlying, futures, spot, onPick }: {
  open: boolean; onClose: () => void; underlying: string; futures: FutureRow[];
  /** spot price of the underlying (live when available); premium is not shown without it */
  spot: number | null; onPick: (f: FutureRow) => void;
}) {
  // live prices over the websocket (falls back to the quote the API returned)
  const base = useMemo(() => futures.map((f) => ({
    ...f, exchange: f.exchange ?? "NFO", ltp: f.ltp ?? null, prev_close: f.prev_close ?? null, change: f.change ?? null, pct: f.pct ?? null,
  })), [futures]);
  const rows = useLiveRows(base);
  return (
    <Sheet open={open} onClose={onClose} label="Futures">
      <div className="overflow-y-auto px-5 lg:px-6 pb-[calc(20px+env(safe-area-inset-bottom))]">
        <h2 className="font-serif text-[25px] lg:text-[30px] text-center pt-3 pb-4">Futures</h2>
        {rows.length === 0 && <div className="py-10 text-center text-muted">No futures contracts for {underlying}.</div>}
        {rows.map((f) => {
          const ltp = f.ltp != null ? Number(f.ltp) : null;
          const prem = ltp != null && spot ? ltp - spot : null;
          return (
            <button key={f.symbol} onClick={() => onPick(f)}
                    className="w-full text-left py-5 border-b border-line last:border-0 active:bg-soft press">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[16px] lg:text-[18px] truncate">{futureName(underlying, f.expiry)}</div>
                  <div className="text-[14px] lg:text-[15px] text-muted mt-1">{f.exchange === "MCX" ? "MCX" : "NSE"}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[16px] lg:text-[18px] font-medium tabular-nums">{ltp != null ? price(ltp) : "—"}</div>
                  {f.change != null && f.pct != null && (
                    <div className={`text-[14px] lg:text-[15px] mt-1 tabular-nums ${pnlClass(f.change)}`}>{signed(Number(f.change))} ({Math.abs(Number(f.pct)).toFixed(2)}%)</div>
                  )}
                </div>
              </div>
              <div className="flex items-start justify-between gap-3 mt-3">
                <div>
                  <div className="text-[14px] lg:text-[15px] text-muted">Open Interest</div>
                  <div className="text-[15px] lg:text-[16px] mt-1 tabular-nums">{f.oi ? f.oi.toLocaleString("en-IN") : "—"}</div>
                </div>
                <div className="text-right">
                  <div className="text-[14px] lg:text-[15px] text-muted">Premium to spot</div>
                  <div className={`text-[15px] lg:text-[16px] mt-1 tabular-nums ${prem != null ? pnlClass(prem) : ""}`}>
                    {prem != null && spot ? `${signed(prem)} (${signed((prem / spot) * 100)}%)` : "—"}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
        <div className="pt-3 text-[12px] lg:text-[13px] text-faint text-center">Lot size {futures[0]?.lot_size ?? "—"} · tap a contract to trade it</div>
      </div>
    </Sheet>
  );
}
