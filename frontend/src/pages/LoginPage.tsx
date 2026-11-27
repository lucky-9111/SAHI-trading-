import { useState, type FormEvent } from "react";
import { Brand } from "../components/Brand";
import { useAuth } from "../contexts/AuthContext";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, name, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full grid place-items-center p-4">
      <form onSubmit={submit} className="panel w-full max-w-sm p-6 space-y-4">
        <Brand />
        <p className="text-xs text-muted">Paper trading only. No real orders, no real money.</p>
        {mode === "register" && (
          <input className="input" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        )}
        <input className="input" type="email" placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" type="password" placeholder="Password (min 8 characters)" minLength={8}
               value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <div role="alert" className="text-sm text-down">{error}</div>}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
        </button>
        <button type="button" className="text-xs text-muted hover:text-slate-900 w-full"
                onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "New here? Create an account" : "Already registered? Log in"}
        </button>
      </form>
    </div>
  );
}
