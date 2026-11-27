import { describe, expect, it } from "vitest";
import type { Dashboard } from "../types";
import { liveKpis, positionPnl } from "./liveKpi";

const dash = (): Dashboard => ({
  account: { id: 1, name: "Main" },
  capital: { initial_capital: 1000000, available_balance: 900000, blocked_funds: 0, invested_amount: 100000, total_virtual_capital: 1000500 },
  pnl: { realized: 200, unrealized: 300, total: 500, return_pct: 0.05 },
  stats: { open_positions: 2, total_trades: 1, win_rate: 100, current_drawdown: 0, daily_risk_used: 0 },
  recent_trades: [],
  open_positions: [
    { id: 1, symbol: "RELIANCE", side: "BUY", quantity: 10, avg_price: "1000", current_price: "1030", unrealized_pnl: "300", exchange: "NSE", token: "2885", entry_value: "10000" },
    { id: 2, symbol: "GOLD", side: "SELL", quantity: 100, avg_price: "1250", current_price: "1250", unrealized_pnl: "0", exchange: "MCX", token: "495213", entry_value: "125000" },
  ],
  has_trades: true, prices_available: true, orders_today: 0,
})

describe("live KPIs", () => {
  it("long and short unrealized P&L follow the live price", () => {
    const p = dash().open_positions
    expect(positionPnl(p[0], 1050)).toBe(500)          // long: (1050 - 1000) x 10
    expect(positionPnl(p[1], 1240)).toBe(1000)         // short: (1250 - 1240) x 100
  })
  it("without a tick the server's number is kept, without either it is null", () => {
    const p = dash().open_positions
    expect(positionPnl(p[0])).toBe(300)
    expect(positionPnl({ ...p[0], unrealized_pnl: null }, undefined)).toBeNull()
  })
  it("recomputes unrealized, total P&L, virtual capital and return", () => {
    const k = liveKpis(dash(), { "NSE:2885": 1050, "MCX:495213": 1240 })
    expect(k.unrealized).toBe(1500)
    expect(k.total).toBe(1700)                          // 200 realized + 1500
    expect(k.totalCapital).toBe(900000 + 100000 + 1500)
    expect(k.returnPct).toBeCloseTo(0.17)
    expect(k.allLive).toBe(true)
  })
  it("a position without a live price keeps its server value and the cards are not marked live", () => {
    const k = liveKpis(dash(), { "NSE:2885": 1050 })
    expect(k.unrealized).toBe(500 + 0)
    expect(k.allLive).toBe(false)
  })
  it("no open positions: unrealized is exactly zero", () => {
    const d = dash(); d.open_positions = []
    expect(liveKpis(d, {}).unrealized).toBe(0)
  })
})
