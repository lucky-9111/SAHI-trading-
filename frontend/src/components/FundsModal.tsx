import { useState, type FormEvent } from "react";
import { api } from "../services/api";
import { Sheet } from "./ui";

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
    <Sheet open onClose={onClose} label={mode === "deposit" ? "Add money" : "Withdraw"}>
      <form onSubmit={submit} className="px-6 pt-3 pb-[calc(24px+env(safe-area-inset-bottom))] space-y-5">
        <h2 className="text-[19px] lg:text-[22px]">{mode === "deposit" ? "Add virtual money" : "Withdraw virtual money"}</h2>
        <div className="flex gap-2 overflow-x-auto no-scrollbar">
          {["10000", "50000", "100000", "500000"].map((v) => (
            <button key={v} type="button" onClick={() => setAmount(v)} className={amount === v ? "chip-on" : "chip"}>₹{Number(v).toLocaleString("en-IN")}</button>
          ))}
        </div>
        <input className="input text-[19px] lg:text-[22px] text-right" type="number" min="0.01" step="0.01" placeholder="₹ Amount" inputMode="decimal" value={amount}
               onChange={(e) => setAmount(e.target.value)} required autoFocus />
        <input className="input" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        {error && <div role="alert" className="text-[13px] lg:text-[14px] text-down">{error}</div>}
        <button className="btn-pill w-full" disabled={busy}>{busy ? "Saving…" : mode === "deposit" ? "Add money" : "Withdraw"}</button>
        <p className="text-center text-[12px] lg:text-[13px] text-faint">Paper trading: this is virtual money, no bank is involved.</p>
      </form>
    </Sheet>
  );
}
