import { useCallback, useEffect, useState } from "react";
import FundsModal from "../components/FundsModal";
import { BackBar, PageTitle, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { LedgerEntry } from "../types";
import { inr, istTime, pnlClass } from "../utils/format";

const TYPE: Record<string, string> = { DEPOSIT: "Added", WITHDRAWAL: "Withdrawn", ORDER_FILL: "Order fill", POSITION_EXIT: "Position exit", INITIAL: "Opening capital" };

export default function FundsPage() {
  const { accountId, accounts, refreshAccounts } = useAuth();
  const [rows, setRows] = useState<LedgerEntry[] | null>(null);
  const [modal, setModal] = useState<"deposit" | "withdraw" | null>(null);
  const [error, setError] = useState("");
  const acc = accounts.find((a) => a.id === accountId);

  const load = useCallback(() => {
    if (!accountId) return;
    api<LedgerEntry[]>(`/api/accounts/${accountId}/ledger`).then(setRows).catch((e) => setError(e.message));
  }, [accountId]);
  useEffect(load, [load]);

  if (!acc) return <div className="p-6 text-muted">Create a portfolio from Home first.</div>;
  return (
    <div className="lg:max-w-[760px]">
      <div className="lg:hidden"><BackBar /></div>
      <PageTitle>Funds</PageTitle>
      <div className="mx-4 lg:mx-0 card px-6 py-6 text-center">
        <div className="text-[14px] lg:text-[15px] text-muted">Available balance · {acc.name}</div>
        <div className="text-[28px] lg:text-[34px] font-medium mt-1">{inr(acc.balance)}</div>
        <div className="grid grid-cols-2 gap-3 mt-5">
          <button className="btn-outline py-3.5 text-[15px] lg:text-[16px]" onClick={() => setModal("withdraw")}>Withdraw</button>
          <button className="btn-primary py-3.5 text-[15px] lg:text-[16px]" onClick={() => setModal("deposit")}>Add money</button>
        </div>
      </div>
      {error && <div role="alert" className="mx-4 lg:mx-0 mt-3 text-[13px] lg:text-[14px] text-down">{error}</div>}
      <h2 className="h2 px-4 lg:px-0 mt-8 mb-1">Ledger</h2>
      <div className="px-4 lg:px-0">
        {rows === null ? <Skeleton rows={5} /> : rows.length === 0 ? <div className="py-10 text-center text-muted">No entries yet.</div> : rows.map((r) => (
          <div key={r.id} className="row items-start">
            <div className="min-w-0">
              <div className="row-name">{TYPE[r.entry_type] ?? r.entry_type}</div>
              <div className="row-sub truncate">{r.description} · {istTime(r.created_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
            </div>
            <div className="text-right shrink-0">
              <div className={`row-price ${pnlClass(r.amount)}`}>{inr(r.amount, true)}</div>
              <div className="row-chg text-muted">Bal {inr(r.balance_after)}</div>
            </div>
          </div>
        ))}
      </div>
      {modal && accountId && <FundsModal accountId={accountId} mode={modal} onClose={() => setModal(null)} onDone={() => { load(); refreshAccounts(); }} />}
    </div>
  );
}
