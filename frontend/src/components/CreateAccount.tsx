import { useState, type FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { Account } from "../types";

export default function CreateAccount({ onCreated }: { onCreated?: () => void }) {
  const { refreshAccounts, setAccountId } = useAuth();
  const [name, setName] = useState("Main Portfolio");
  const [capital, setCapital] = useState("1000000");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const acc = await api<Account>("/api/accounts", { method: "POST", json: { name, initial_capital: capital } });
      await refreshAccounts();
      setAccountId(acc.id);
      onCreated?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="panel p-5 space-y-3 max-w-md">
      <h2 className="font-semibold">Create virtual portfolio</h2>
      <label className="block text-xs text-muted">Name
        <input className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="block text-xs text-muted">Initial virtual capital (₹)
        <input className="input mt-1" type="number" min="1" step="0.01" value={capital}
               onChange={(e) => setCapital(e.target.value)} required />
      </label>
      {error && <div role="alert" className="text-sm text-down">{error}</div>}
      <button className="btn-primary" disabled={busy}>{busy ? "Creating…" : "Create portfolio"}</button>
    </form>
  );
}
