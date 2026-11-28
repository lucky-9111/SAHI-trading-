import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { Segmented } from "./ui";

interface Settings { after_hours_mode: "QUEUE" | "REJECT"; slippage_pct: string | null; default_slippage_pct: string; depth_fills: boolean }

/** Per-portfolio order handling. Stored and enforced by the backend. */
export default function OrderSettings() {
  const { accountId } = useAuth();
  const [s, setS] = useState<Settings | null>(null);
  const [slip, setSlip] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const base = `/api/accounts/${accountId}/order-settings`;

  useEffect(() => {
    if (!accountId) return;
    api<Settings>(base).then((r) => { setS(r); setSlip(r.slippage_pct ?? ""); }).catch((e) => setMsg({ ok: false, text: e.message }));
  }, [accountId, base]);

  const save = async (mode: Settings["after_hours_mode"], slippage: string) => {
    try {
      const r = await api<Settings>(base, { method: "PUT", json: { after_hours_mode: mode, slippage_pct: slippage === "" ? null : slippage } });
      setS(r); setMsg({ ok: true, text: "Saved" }); setTimeout(() => setMsg(null), 2500);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  if (!s) return null;
  return (
    <div>
      <div className="text-[15px] lg:text-[16px] text-muted mb-2 px-1">Order settings</div>
      <div className="card divide-y divide-line">
        <div className="px-5 py-4 space-y-3">
          <div className="text-[16px] lg:text-[17px]">When the market is closed</div>
          <Segmented label="After-market orders" items={[["QUEUE", "Queue (AMO)"], ["REJECT", "Reject"]]} value={s.after_hours_mode}
                     onChange={(v) => save(v, slip)} />
          <div className="text-[13px] lg:text-[14px] text-muted">
            {s.after_hours_mode === "QUEUE"
              ? "Orders are kept as Pending and execute at the first fresh live price of the next session, never at the previous close. Unfilled day orders expire at that session's close."
              : "New day orders are rejected while the exchange is closed (GTT orders are still accepted)."}
          </div>
        </div>
        <div className="px-5 py-4 space-y-2">
          <label className="flex items-center justify-between gap-3">
            <span className="text-[16px] lg:text-[17px]">Slippage %</span>
            <input aria-label="Slippage percent" className="input !w-[120px] text-right" type="number" min="0" max="5" step="0.01" inputMode="decimal"
                   placeholder={s.default_slippage_pct} value={slip} onChange={(e) => setSlip(e.target.value)} onBlur={() => save(s.after_hours_mode, slip)} />
          </label>
          <div className="text-[13px] lg:text-[14px] text-muted">
            Adverse slippage on market and stop-market fills (empty = server default {s.default_slippage_pct}%).
            {s.depth_fills ? " Fills also use the live bid/ask depth when the broker provides it, so large orders can fill partially." : " Fills use the last traded price."}
          </div>
        </div>
      </div>
      {msg && <div role="status" className={`mt-2 px-1 text-[13px] ${msg.ok ? "text-up" : "text-down"}`}>{msg.text}</div>}
    </div>
  );
}
