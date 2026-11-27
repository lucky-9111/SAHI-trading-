import { useCallback, useEffect, useState } from "react";
import FundsModal from "../components/FundsModal";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { LedgerEntry } from "../types";
import { inr, pnlClass } from "../utils/format";

export default function FundsPage() {
  const { accountId, accounts, refreshAccounts } = useAuth();
  const [rows, setRows] = useState<LedgerEntry[]>([]);
  const [modal, setModal] = useState<"deposit" | "withdraw" | null>(null);
  const [error, setError] = useState("");
  const acc = accounts.find((a) => a.id === accountId);

  const load = useCallback(() => {
    if (!accountId) return;
    api<LedgerEntry[]>(`/api/accounts/${accountId}/ledger`).then(setRows).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(load, [load]);

  if (!acc) return <div className="text-muted">Create a portfolio from the Dashboard first.</div>;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Funds · {acc.name}</h1>
          <div className="text-sm text-muted">Available: <span className="text-slate-900 font-medium">{inr(acc.balance)}</span></div>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => setModal("withdraw")}>Withdraw</button>
          <button className="btn-primary" onClick={() => setModal("deposit")}>Add Funds</button>
        </div>
      </div>
      {error && <div role="alert" className="text-down">{error}</div>}
      <div className="panel overflow-x-auto">
        <table className="w-full">
          <thead><tr className="border-b border-line">
            <th className="th">Date</th><th className="th">Type</th><th className="th">Description</th>
            <th className="th text-right">Amount</th><th className="th text-right">Balance</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-line/50">
                <td className="td">{new Date(r.created_at).toLocaleString("en-IN")}</td>
                <td className="td">{r.entry_type}</td><td className="td text-muted">{r.description}</td>
                <td className={`td text-right ${pnlClass(r.amount)}`}>{inr(r.amount, true)}</td>
                <td className="td text-right">{inr(r.balance_after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {modal && accountId && (
        <FundsModal accountId={accountId} mode={modal} onClose={() => setModal(null)}
                    onDone={() => { load(); refreshAccounts(); }} />
      )}
    </div>
  );
}
