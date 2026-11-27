import { LineChart } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useLiveLtps, useOrdersChanged } from "../utils/liveSocket";
import { keyOfPosition, liveKpis, positionPnl } from "../utils/liveKpi";
import { api } from "../services/api";
import type { Dashboard } from "../types";
import { inr, pnlClass } from "../utils/format";

export interface PositionRow {
  id: number; symbol: string; side: string; product: string; quantity: number; avg_price: string;
  current_price: string | null; invested_amount: string; stop_loss: string | null; target: string | null;
  unrealized_pnl: string | null; pnl_pct: string | null; strategy: string; opened_at: string;
  instrument_type: string; lot_size: number; expiry: string | null; chart_symbol: string; chart_exchange: string;
  exchange?: string; token?: string; entry_value?: string | null;
}

function Row({ p, accountId, onChange, setMsg, ltp }: {
  p: PositionRow; accountId: number; onChange: () => void; setMsg: (m: { ok: boolean; text: string }) => void; ltp?: number;
}) {
  // live price -> current price, unrealized P&L and % (same basis as the server); without a fresh tick the server's numbers stay
  const pnl = positionPnl({ side: p.side, quantity: p.quantity, entry_value: p.entry_value, unrealized_pnl: p.unrealized_pnl }, ltp);
  const cur = ltp != null ? String(ltp) : p.current_price;
  const pct = pnl != null && Number(p.invested_amount) ? ((pnl / Number(p.invested_amount)) * 100).toFixed(2) : p.pnl_pct;
  const [qty, setQty] = useState("");
  const [sl, setSl] = useState(p.stop_loss ?? "");
  const [tg, setTg] = useState(p.target ?? "");
  const [editing, setEditing] = useState(false);
  const base = `/api/accounts/${accountId}/positions/${p.id}`;

  const exit = async () => {
    const n = qty ? Number(qty) : p.quantity;
    if (!window.confirm(`Exit ${n} of ${p.quantity} ${p.symbol} at market?`)) return;
    try {
      const t = await api<{ net_pnl: string; exit_price: string }>(`${base}/exit`, { method: "POST", json: { quantity: qty ? Number(qty) : undefined } });
      setMsg({ ok: true, text: `Exited ${n} ${p.symbol} at ${inr(t.exit_price)}. Net P&L ${inr(t.net_pnl, true)}` });
      setQty(""); onChange();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const save = async () => {
    try {
      await api(base, { method: "PATCH", json: {
        stop_loss: sl || undefined, target: tg || undefined, clear_stop_loss: !sl && !!p.stop_loss, clear_target: !tg && !!p.target } });
      setMsg({ ok: true, text: `Updated ${p.symbol} stop loss / target` }); setEditing(false); onChange();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  return (
    <tr className="border-b border-line/50 align-top">
      <td className="td font-medium">{p.symbol}
        <div className="text-[11px] text-muted">
          {p.product} · {p.strategy}
          {p.instrument_type !== "EQ" && ` · ${p.quantity / p.lot_size} lot(s)`}
        </div>
      </td>
      <td className={`td ${p.side === "BUY" ? "text-up" : "text-down"}`}>{p.side}</td>
      <td className="td text-right">{p.quantity}</td>
      <td className="td text-right">{inr(p.avg_price)}</td>
      <td className="td text-right">{cur ? inr(cur) : "—"}</td>
      <td className="td text-right">{inr(p.invested_amount)}</td>
      <td className="td text-right">
        {editing ? <input className="input !w-24 !py-1" type="number" step="0.05" value={sl} onChange={(e) => setSl(e.target.value)} /> : p.stop_loss ? inr(p.stop_loss) : "—"}
      </td>
      <td className="td text-right">
        {editing ? <input className="input !w-24 !py-1" type="number" step="0.05" value={tg} onChange={(e) => setTg(e.target.value)} /> : p.target ? inr(p.target) : "—"}
      </td>
      <td className={`td text-right ${pnl != null ? pnlClass(pnl) : ""}`}>
        {pnl != null ? inr(pnl, true) : "—"}
        {pct && <div className="text-[11px]">{pct}%</div>}
      </td>
      <td className="td">
        <div className="flex gap-1 items-center justify-end">
          <Link className="btn-ghost !py-1" to={`/trade?symbol=${p.chart_symbol}&exchange=${p.chart_exchange}`}
                title={`Open ${p.chart_symbol} chart`}><LineChart size={14} /> Chart</Link>
          <input className="input !w-16 !py-1" type="number" min="1" max={p.quantity} placeholder="Qty" value={qty}
                 onChange={(e) => setQty(e.target.value)} aria-label="Exit quantity" />
          <button className="btn-ghost !py-1" onClick={exit}>{qty ? "Partial exit" : "Exit"}</button>
          {editing
            ? <button className="btn-primary !py-1" onClick={save}>Save</button>
            : <button className="btn-ghost !py-1" onClick={() => setEditing(true)}>SL/TGT</button>}
        </div>
      </td>
    </tr>
  );
}

export default function PositionsPage() {
  const { accountId, refreshAccounts } = useAuth();
  const [rows, setRows] = useState<PositionRow[] | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!accountId) return;
    api<PositionRow[]>(`/api/accounts/${accountId}/positions`).then((r) => { setRows(r); setError(""); }).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useOrdersChanged(load);   // a fill, stop, target or square-off: refresh now instead of waiting for the next poll

  const [dash, setDash] = useState<Dashboard | null>(null);
  useEffect(() => {
    if (!accountId) return;
    const loadDash = () => api<Dashboard>(`/api/accounts/${accountId}/dashboard`).then(setDash).catch(() => {});
    loadDash();
    const t = setInterval(loadDash, 10000);
    return () => clearInterval(t);
  }, [accountId, rows]);

  const keys = useMemo(() => [...(rows ?? []), ...(dash?.open_positions ?? [])].map((p) => keyOfPosition({ exchange: p.exchange, token: p.token })).filter(Boolean), [rows, dash]);
  const ltps = useLiveLtps(keys);
  const kpi = dash ? liveKpis(dash, ltps) : null;
  if (!accountId) return <div className="text-muted">Create a portfolio first.</div>;
  const total = (rows ?? []).reduce((a, r) => a + (positionPnl({ side: r.side, quantity: r.quantity, entry_value: r.entry_value, unrealized_pnl: r.unrealized_pnl }, ltps[keyOfPosition({ exchange: r.exchange, token: r.token })]) ?? 0), 0);
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Portfolio</h1>
      {dash && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            ["Total virtual capital", inr(kpi!.totalCapital), ""],
            ["Available balance", inr(kpi!.available), ""],
            ["Invested capital", inr(kpi!.invested), ""],
            ["Open positions", String(dash.stats.open_positions), ""],
            ["Realized P&L", inr(dash.pnl.realized, true), pnlClass(dash.pnl.realized)],
            ["Unrealized P&L", inr(kpi!.unrealized, true), pnlClass(kpi!.unrealized)],
            ["Total P&L", inr(kpi!.total, true), pnlClass(kpi!.total)],
            ["Total return", `${kpi!.returnPct.toFixed(2)}%`, pnlClass(kpi!.returnPct)],
          ].map(([label, value, cls]) => (
            <div key={label} className="panel px-4 py-3">
              <div className="text-xs text-muted">{label}</div>
              <div className={`mt-0.5 text-lg font-semibold ${cls}`}>{value}</div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Open positions {rows && <span className="text-muted">({rows.length})</span>}</h2>
        {rows && rows.length > 0 && <div className="text-sm">Total unrealized <b className={pnlClass(total)}>{inr(total, true)}</b></div>}
      </div>
      {error && <div role="alert" className="text-down text-sm">{error}</div>}
      {msg && <div role="status" className={`text-sm ${msg.ok ? "text-up" : "text-down"}`}>{msg.text}</div>}
      <div className="panel overflow-x-auto">
        <table className="w-full">
          <thead><tr className="border-b border-line">
            <th className="th">Stock</th><th className="th">Side</th><th className="th text-right">Qty</th>
            <th className="th text-right">Avg</th><th className="th text-right">LTP</th><th className="th text-right">Invested</th>
            <th className="th text-right">SL</th><th className="th text-right">Target</th><th className="th text-right">P&amp;L</th>
            <th className="th text-right">Actions</th></tr></thead>
          <tbody>
            {rows?.map((p) => <Row key={p.id} p={p} accountId={accountId} setMsg={setMsg} ltp={ltps[keyOfPosition({ exchange: p.exchange, token: p.token })]}
                                   onChange={() => { load(); refreshAccounts(); }} />)}
          </tbody>
        </table>
        {rows?.length === 0 && <div className="text-sm text-muted py-10 text-center">No open positions. Place an order from the Trade page.</div>}
      </div>
      <div className="text-xs text-muted">Stop-loss and target are checked by the backend every few seconds while the market is open (9:15 to 15:30 IST).</div>
    </div>
  );
}
