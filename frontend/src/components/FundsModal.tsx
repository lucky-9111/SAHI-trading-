import { useState, type FormEvent } from "react";
import { api } from "../services/api";

export default function FundsModal({ accountId, mode, onClose, onDone }: {
  accountId: number; mode: "deposit" | "withdraw"; onClose: () => void; onDone: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      await api(`/api/accounts/${accountId}/${mode}`, { method: "POST", json: { amount, note } });
      onDone(); onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 grid place-items-center p-4 z-50" role="dialog" aria-modal="true">
      <form onSubmit={submit} className="panel w-full max-w-sm p-5 space-y-3">
        <h2 className="font-semibold">{mode === "deposit" ? "Add virtual funds" : "Withdraw virtual funds"}</h2>
        <input className="input" type="number" min="0.01" step="0.01" placeholder="Amount (₹)" value={amount}
               onChange={(e) => setAmount(e.target.value)} required autoFocus />
        <input className="input" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        {error && <div role="alert" className="text-sm text-down">{error}</div>}
        <div className="flex gap-2 justify-end">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : "Confirm"}</button>
        </div>
      </form>
    </div>
  );
}
