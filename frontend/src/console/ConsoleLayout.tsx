import {
  Activity, BarChart3, CalendarDays, CircleAlert, FileClock, Flag, Info, KeyRound, LogOut, Megaphone, ScrollText, Shield, ShieldCheck,
  ToggleRight, UserCheck, Users, type LucideIcon,
} from "lucide-react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Badge, usePoll } from "./kit";

type Item = [string, string, LucideIcon];
const ADMIN: Item[] = [
  ["/admin", "Overview", Activity], ["/admin/users", "Users", Users], ["/admin/audit", "Audit log", ShieldCheck],
  ["/admin/announcements", "Announcements", Megaphone], ["/admin/calendar", "Market calendar", CalendarDays],
];
const DEV: Item[] = [
  ["/dev", "System health", Activity], ["/dev/angel", "Angel One API", BarChart3], ["/dev/errors", "Errors", CircleAlert],
  ["/dev/switches", "Switches", ToggleRight], ["/dev/sessions", "Sessions", UserCheck], ["/dev/logins", "Login attempts", KeyRound],
  ["/dev/roles", "Roles & permissions", Flag], ["/dev/info", "System info", Info], ["/dev/logs", "Live logs", ScrollText],
];

interface Status { system: string; nse: string; mcx: string; nse_open: boolean; mcx_open: boolean; orders_enabled: boolean; engine_enabled: boolean }

function TopPills() {
  const { data } = usePoll<Status>("/api/admin/status", 15000);
  if (!data) return null;
  const sys = { ok: ["System OK", "bg-up"], warn: ["System: check", "bg-amber-400"], fail: ["System problem", "bg-sell"] }[data.system] ?? ["System", "bg-faint"];
  const pill = "inline-flex items-center gap-2 rounded-full border border-line bg-white px-3.5 py-1.5 text-[13px] whitespace-nowrap";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Link to="/dev" className={pill}><span className={`h-2 w-2 rounded-full ${sys[1]}`} />{sys[0]}</Link>
      <span className={pill}><span className={`h-2 w-2 rounded-full ${data.nse_open || data.mcx_open ? "bg-up" : "bg-faint"}`} />NSE {data.nse_open ? "open" : "closed"} · MCX {data.mcx_open ? "open" : "closed"}</span>
      <span className={pill}><b className="text-[#b26a00] font-semibold">PAPER</b>{!data.orders_enabled ? <span className="text-sell">orders paused</span> : !data.engine_enabled ? <span className="text-sell">engine paused</span> : <span className="text-muted">trading on</span>}</span>
    </div>
  );
}

export default function ConsoleLayout({ kind }: { kind: "admin" | "dev" }) {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  if (!user) return null;
  const allowed = kind === "admin" ? user.role === "admin" || user.role === "developer" : user.role === "developer";
  if (!allowed || user.read_only) return <Navigate to="/" replace />;
  const items = kind === "admin" ? ADMIN : DEV;
  const current = [...items].sort((a, b) => b[0].length - a[0].length).find(([p]) => pathname === p || pathname.startsWith(p + "/"));
  const Logo = kind === "admin" ? Users : Shield;
  return (
    <div className="min-h-full bg-[#f4f6f9]">
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-[236px] flex-col border-r border-line bg-white z-30">
        <div className="h-[76px] px-5 flex items-center gap-3">
          <span className={`h-10 w-10 rounded-xl grid place-items-center text-white ${kind === "admin" ? "bg-[#6d4aff]" : "bg-[#1f6feb]"}`}><Logo size={20} /></span>
          <div className="leading-tight"><div className="font-semibold text-[16px]">{kind === "admin" ? "Admin console" : "Developer console"}</div>
            <div className="text-[11.5px] text-muted">{kind === "admin" ? "People and access" : "Health and fault isolation"}</div></div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
          {items.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === "/admin" || to === "/dev"}
                     className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] transition-colors ${isActive ? "bg-soft text-ink font-semibold" : "text-[#444] hover:bg-soft"}`}>
              <Icon size={18} strokeWidth={1.7} />{label}
            </NavLink>
          ))}
          <div className="text-[11px] uppercase tracking-wider text-faint px-3 pt-5 pb-1">Go to</div>
          <Link to="/" className="flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] text-[#444] hover:bg-soft"><BarChart3 size={18} strokeWidth={1.7} />Trading app</Link>
          {kind === "admin" && user.role === "developer" && <Link to="/dev" className="flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] text-[#444] hover:bg-soft"><Shield size={18} strokeWidth={1.7} />Developer console</Link>}
          {kind === "dev" && <Link to="/admin" className="flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] text-[#444] hover:bg-soft"><Users size={18} strokeWidth={1.7} />Admin console</Link>}
        </nav>
        <div className="m-3 rounded-2xl bg-soft px-3 py-2.5">
          <div className="text-[13.5px] font-medium truncate">{user.name}</div>
          <div className="text-[12px] text-muted">{user.role}{user.is_owner ? " · owner" : ""}</div>
          <button onClick={logout} className="mt-2 flex items-center gap-2 text-[13px] text-sell"><LogOut size={15} />Sign out</button>
        </div>
      </aside>

      <div className="lg:pl-[236px]">
        <header className="sticky top-0 z-20 bg-white/90 backdrop-blur border-b border-line px-4 lg:px-8 py-3 flex flex-wrap items-center gap-3">
          <Badge tone={kind === "admin" ? "dark" : "info"}>{kind === "admin" ? "Admin" : "Developer"}</Badge>
          <span className="text-[15px] font-medium">{current?.[1]}</span>
          <div className="flex-1" />
          <TopPills />
        </header>
        <nav className="lg:hidden flex gap-2 overflow-x-auto no-scrollbar px-4 py-3 bg-white border-b border-line">
          {items.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/admin" || to === "/dev"} className={({ isActive }) => isActive ? "chip-on" : "chip"}>{label}</NavLink>
          ))}
          <Link to="/" className="chip"><FileClock size={14} />App</Link>
        </nav>
        <main className="px-4 lg:px-8 py-5 lg:py-7 max-w-[1400px]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
