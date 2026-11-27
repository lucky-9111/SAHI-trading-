import type { Dashboard } from "../types";

type Pos = Dashboard["open_positions"][number];

/** Unrealized P&L of one open position at `ltp`, on the same basis as the server (contract value at entry, before exit charges).
 *  Without a live price it is the server's number; without either, null. */
export function positionPnl(p: Pick<Pos, "side" | "quantity" | "entry_value" | "unrealized_pnl">, ltp?: number): number | null {
  if (ltp != null && p.entry_value != null && p.entry_value !== "") {
    const value = ltp * p.quantity
    const entry = Number(p.entry_value)
    return p.side === "BUY" ? value - entry : entry - value
  }
  return p.unrealized_pnl != null ? Number(p.unrealized_pnl) : null
}

export const keyOfPosition = (p: Pick<Pos, "exchange" | "token">): string => (p.exchange && p.token ? `${p.exchange}:${p.token}` : "")

export interface LiveKpis {
  unrealized: number; total: number; totalCapital: number; returnPct: number; invested: number; available: number; realized: number
  /** true when every open position was priced from a live tick */
  allLive: boolean
}

/** The dashboard's KPI cards recomputed from live prices. Realized P&L, balance and invested amount do not depend on the price. */
export function liveKpis(d: Dashboard, ltps: Record<string, number>): LiveKpis {
  let unrealized = 0
  let allLive = true
  for (const p of d.open_positions) {
    const k = keyOfPosition(p)
    const live = k ? ltps[k] : undefined
    if (live == null) allLive = false
    unrealized += positionPnl(p, live) ?? 0
  }
  if (d.open_positions.length === 0) unrealized = 0
  const realized = Number(d.pnl.realized)
  const invested = Number(d.capital.invested_amount)
  const available = Number(d.capital.available_balance)
  const total = realized + unrealized
  const initial = Number(d.capital.initial_capital)
  return { unrealized, total, totalCapital: available + invested + unrealized, returnPct: initial ? (total / initial) * 100 : 0, invested, available, realized, allLive }
}
