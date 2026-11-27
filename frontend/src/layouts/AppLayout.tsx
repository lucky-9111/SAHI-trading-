import { Bell, IndianRupee, LogOut, Menu, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Brand } from "../components/Brand";
import StockSearch from "../components/StockSearch";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr } from "../utils/format";
import { NAV } from "./nav";

interface Feed { state: string; reason: string }

export default function AppLayout() {
  const { user, accounts, accountId, setAccountId, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [feed, setFeed] = useState<Feed | null>(null);
  const acc = accounts.find((a) => a.id === accountId);

  useEffect(() => {
    const load = () => api<Feed>("/api/market/status").then(setFeed).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const dot = feed?.state === "DELAYED" ? "bg-amber-400" : feed?.state === "LIVE" ? "bg-up" : "bg-slate-300";
  return (
    <div className="h-full flex bg-bg">
      <aside className={`${collapsed ? "w-[68px]" : "w-60"} shrink-0 border-r border-line bg-white flex flex-col transition-all`}>
        <div className="h-16 px-4 flex items-center justify-between">
          <Brand compact={collapsed} />
          {!collapsed && (
            <button aria-label="Toggle sidebar" className="text-muted hover:text-slate-900" onClick={() => setCollapsed(true)}>
              <Menu size={18} />
            </button>
          )}
        </div>
        {collapsed && (
          <button aria-label="Expand sidebar" className="mx-auto mb-1 text-muted hover:text-slate-900" onClick={() => setCollapsed(false)}>
            <Menu size={18} />
          </button>
        )}
        <nav className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
          {NAV.map(({ path, label, icon: Icon, phase }) => (
            <NavLink key={path} to={path} end={path === "/"} title={label}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm ${
                  isActive ? "bg-slate-900 text-white font-medium" : "text-slate-600 hover:bg-panel2"}`}>
              <Icon size={19} className="shrink-0" />
              {!collapsed && <span className="flex-1">{label}</span>}
              {!collapsed && phase && <span className="text-[10px] opacity-60">Soon</span>}
            </NavLink>
          ))}
        </nav>
        <button onClick={logout} className="m-2 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-600 hover:bg-panel2">
          <LogOut size={19} />{!collapsed && "Logout"}
        </button>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-16 shrink-0 border-b border-line bg-white px-5 flex items-center gap-3">
          <StockSearch />
          <div className="hidden lg:flex items-center gap-2 text-xs text-muted" title={feed?.reason ?? ""}>
            <span className={`h-2 w-2 rounded-full ${dot}`} /> Data: {feed?.state ?? "DISCONNECTED"}
          </div>
          <div className="flex-1" />
          {accounts.length > 1 && (
            <select aria-label="Account" className="input !w-auto !rounded-full" value={accountId ?? ""}
                    onChange={(e) => setAccountId(Number(e.target.value))}>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
          <Link to="/funds" title="Virtual funds" className="flex items-center gap-1.5 rounded-full border border-line px-3.5 py-2 text-sm hover:bg-panel2">
            <IndianRupee size={15} /><span className="font-medium">{acc ? inr(acc.balance).replace("₹", "") : "0.00"}</span>
          </Link>
          <button aria-label="Notifications" className="h-10 w-10 grid place-items-center rounded-full bg-panel2 text-slate-700"><Bell size={18} /></button>
          <Link to="/settings" aria-label="Settings" className="h-10 w-10 grid place-items-center rounded-full bg-panel2 text-slate-700"><Settings size={18} /></Link>
          <div title={user?.email} className="h-10 w-10 rounded-full bg-slate-900 text-white grid place-items-center text-sm font-semibold">
            {user?.name?.[0]?.toUpperCase()}
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-5 bg-soft"><Outlet /></main>
      </div>
    </div>
  );
}
