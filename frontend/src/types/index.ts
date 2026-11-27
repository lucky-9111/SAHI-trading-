export interface User { id: number; email: string; name: string }
export interface Account { id: number; name: string; initial_capital: string; balance: string }
export interface LedgerEntry {
  id: number; entry_type: string; amount: string; balance_after: string; description: string; created_at: string;
}
export interface Dashboard {
  account: { id: number; name: string };
  capital: {
    initial_capital: string | number; available_balance: string | number; blocked_funds: string | number;
    invested_amount: string | number; total_virtual_capital: string | number;
  };
  pnl: { realized: number; unrealized: number; total: number; return_pct: number };
  stats: {
    open_positions: number; total_trades: number; win_rate: number | null; current_drawdown: number;
    daily_risk_used: number;
  };
  recent_trades: { id: number; symbol: string; side: string; quantity: number; exit_price: string; net_pnl: string; exit_time: string }[];
  open_positions: { id: number; symbol: string; side: string; quantity: number; avg_price: string; current_price: string | null; unrealized_pnl: string | null }[];
  has_trades: boolean;
  prices_available: boolean;
  orders_today: number;
}
