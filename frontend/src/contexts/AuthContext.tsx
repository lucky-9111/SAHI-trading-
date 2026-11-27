import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, tokenStore } from "../services/api";
import type { Account, User } from "../types";

interface Ctx {
  user: User | null;
  loading: boolean;
  accounts: Account[];
  accountId: number | null;
  setAccountId: (id: number) => void;
  refreshAccounts: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, name: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthCtx = createContext<Ctx | null>(null);
const ACC_KEY = "agt_account";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountIdState] = useState<number | null>(null);

  const refreshAccounts = useCallback(async () => {
    const list = await api<Account[]>("/api/accounts");
    setAccounts(list);
    setAccountIdState((cur) => {
      const saved = Number(localStorage.getItem(ACC_KEY));
      const pick = [cur, saved].find((id) => id && list.some((a) => a.id === id));
      return pick ?? list[0]?.id ?? null;
    });
  }, []);

  useEffect(() => {
    if (!tokenStore.get()) { setLoading(false); return; }
    api<User>("/api/auth/me")
      .then(async (u) => { setUser(u); await refreshAccounts(); })
      .catch((e) => { if (e instanceof ApiError && e.status === 401) tokenStore.clear(); })
      .finally(() => setLoading(false));
  }, [refreshAccounts]);

  const finish = async (res: { access_token: string; user: User }) => {
    tokenStore.set(res.access_token);
    setUser(res.user);
    await refreshAccounts();
  };

  const value: Ctx = {
    user, loading, accounts, accountId, refreshAccounts,
    setAccountId: (id) => { localStorage.setItem(ACC_KEY, String(id)); setAccountIdState(id); },
    login: async (email, password) => finish(await api("/api/auth/login", { method: "POST", json: { email, password } })),
    register: async (email, name, password) =>
      finish(await api("/api/auth/register", { method: "POST", json: { email, name, password } })),
    logout: () => { tokenStore.clear(); setUser(null); setAccounts([]); setAccountIdState(null); },
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}
