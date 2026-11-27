import { useState, type FormEvent } from "react";
import { AppMark } from "../components/art";
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
    <div className="min-h-full flex flex-col justify-center px-6 py-10 lg:items-center">
      <form onSubmit={submit} className="w-full max-w-[400px] mx-auto space-y-5 animate-fade">
        <AppMark size={56} />
        <div>
          <h1 className="page-title">{mode === "login" ? "Welcome back" : "Create account"}</h1>
          <p className="text-[16px] text-muted mt-2">SAHI Paper Trading · virtual money only, no real orders.</p>
        </div>
        {mode === "register" && <input className="input" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />}
        <input className="input" type="email" placeholder="Email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" type="password" placeholder="Password (min 8 characters)" minLength={8} autoComplete={mode === "login" ? "current-password" : "new-password"}
               value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <div role="alert" className="text-[14px] text-down">{error}</div>}
        <button className="btn-pill w-full" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}</button>
        <button type="button" className="w-full text-[15px] text-muted active:opacity-60"
                onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "New here? Create an account" : "Already registered? Log in"}
        </button>
      </form>
    </div>
  );
}
