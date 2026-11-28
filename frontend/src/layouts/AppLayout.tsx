import { BarChart3, BookOpen, FileText, History, IndianRupee, LogOut, ScanSearch, Search, Settings, Shield, User, Users, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../services/api";
import { Link, NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { AppMark, HomeIcon, OrdersIcon, PortfolioIcon, TradeIcon, WatchIcon } from "../components/art";
import { MarketBar, MarketPill } from "../components/MarketStatus";
import { NotificationBell, NotificationCenter } from "../components/Notifications";
import SearchOverlay, { openSearch } from "../components/search";
import { useAuth } from "../contexts/AuthContext";
import { inr } from "../utils/format";
import { useFeedState } from "../utils/liveSocket";

export const TABS = [
  { path: "/", label: "Home", Icon: HomeIcon },
  { path: "/watchlist", label: "Watchlist", Icon: WatchIcon },
  { path: "/trade", label: "Trade", Icon: TradeIcon },
  { path: "/order-book", label: "Orders", Icon: OrdersIcon },
  { path: "/positions", label: "Portfolio", Icon: PortfolioIcon },
];
const MORE = [
  { path: "/trade-book", label: "Trade history", Icon: History },
  { path: "/funds", label: "Funds", Icon: Wallet },
  { path: "/analytics", label: "Analytics", Icon: BarChart3, soon: true },
  { path: "/journal", label: "Trading journal", Icon: BookOpen, soon: true },
  { path: "/reports", label: "Reports", Icon: FileText, soon: true },
  { path: "/scanner-import", label: "Scanner import", Icon: ScanSearch, soon: true },
  { path: "/settings", label: "Settings", Icon: Settings },
];

function FeedDot() {
  const ws = useFeedState();
  const label = ws === "connected" ? "Live" : ws === "stale" ? "Stale" : ws === "reconnecting" || ws === "offline" ? "Connecting" : ws === "replay" ? "Replay" : "Feed idle";
  const dot = ws === "connected" ? "bg-up" : ws === "stale" || ws === "reconnecting" ? "bg-amber-400" : ws === "replay" ? "bg-blue-500" : "bg-faint";
  return <span className="inline-flex items-center gap-2 text-[12px] lg:text-[13px] text-muted"><span className={`h-2 w-2 rounded-full ${dot} ${ws === "connected" ? "animate-pulse" : ""}`} />{label}</span>;
}

/** Bottom navigation (phones) */
function BottomNav() {
  const { pathname } = useLocation();
  return (
    <nav className="lg:hidden fixed inset-x-0 bottom-0 z-40 bg-white border-t border-line pb-safe">
      <div className="grid grid-cols-5 h-[62px]">
        {TABS.map(({ path, label, Icon }) => {
          const active = path === "/" ? pathname === "/" : pathname.startsWith(path);
          return (
            <Link key={path} to={path} className="flex flex-col items-center justify-center gap-[3px] press">
              <Icon active={active} width={23} height={23} className={active ? "text-ink" : "text-[#555]"} />
              <span className={`text-[12.5px] leading-tight ${active ? "text-ink font-semibold" : "text-[#555]"}`}>{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

/** Left sidebar + top bar (laptops / desktops) */
function DesktopChrome() {
  const { user, accounts, accountId, setAccountId, logout } = useAuth();
  const acc = accounts.find((a) => a.id === accountId);
  const { pathname } = useLocation();
  return (
    <>
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-[248px] flex-col border-r border-line bg-white z-30">
        <Link to="/" className="h-[76px] px-5 flex items-center gap-3">
          <AppMark size={40} />
          <div className="leading-tight"><div className="font-semibold text-[16px] lg:text-[17px]">SAHI Trading</div><div className="text-[11.5px] lg:text-[12px] text-muted">Paper trading · virtual money</div></div>
        </Link>
        <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
          {TABS.map(({ path, label, Icon }) => {
            const active = path === "/" ? pathname === "/" : pathname.startsWith(path);
            return (
              <Link key={path} to={path} className={`flex items-center gap-3 rounded-2xl px-3 py-2.5 text-[14px] lg:text-[15px] transition-colors ${active ? "bg-soft text-ink font-semibold" : "text-[#444] hover:bg-soft"}`}>
                <Icon active={active} width={24} height={24} />{label}
              </Link>
            );
          })}
          <div className="h-px bg-line my-3 mx-3" />
          {(user?.role === "admin" || user?.role === "developer") && !user.read_only && (
            <NavLink to="/admin" className="flex items-center gap-3 rounded-2xl px-3 py-2 text-[13px] lg:text-[14px] text-muted hover:bg-soft hover:text-ink"><Users size={19} strokeWidth={1.7} /><span className="flex-1">Admin console</span></NavLink>)}
          {user?.role === "developer" && !user.read_only && (
            <NavLink to="/dev" className="flex items-center gap-3 rounded-2xl px-3 py-2 text-[13px] lg:text-[14px] text-muted hover:bg-soft hover:text-ink"><Shield size={19} strokeWidth={1.7} /><span className="flex-1">Developer console</span></NavLink>)}
          {MORE.map(({ path, label, Icon, soon }) => (
            <NavLink key={path} to={path} className={({ isActive }) => `flex items-center gap-3 rounded-2xl px-3 py-2 text-[13px] lg:text-[14px] transition-colors ${isActive ? "bg-soft text-ink font-medium" : "text-muted hover:bg-soft hover:text-ink"}`}>
              <Icon size={19} strokeWidth={1.7} /><span className="flex-1">{label}</span>{soon && <span className="text-[10px] uppercase tracking-wide text-faint">Soon</span>}
            </NavLink>
          ))}
        </nav>
        <button onClick={logout} className="m-3 flex items-center gap-3 rounded-2xl px-3 py-2.5 text-[13px] lg:text-[14px] text-sell hover:bg-sellbg/50"><LogOut size={19} />Logout</button>
      </aside>

      <header className="hidden lg:flex fixed top-0 right-0 left-[248px] h-[76px] z-20 bg-white/90 backdrop-blur border-b border-line items-center gap-3 px-8">
        <button onClick={() => openSearch()} className="flex-1 max-w-[520px] h-12 flex items-center gap-3 rounded-full border border-line px-5 text-left text-[15px] lg:text-[16px] text-faint hover:border-[#cfcfcf] transition-colors">
          <Search size={20} className="text-ink" />Search SAHI
        </button>
        <MarketPill />
        <FeedDot />
        <div className="flex-1" />
        <NotificationBell />
        {accounts.length > 1 && (
          <select aria-label="Portfolio" className="h-11 rounded-full border border-line px-4 text-[13px] lg:text-[14px] bg-white" value={accountId ?? ""} onChange={(e) => setAccountId(Number(e.target.value))}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
        <Link to="/funds" title="Virtual funds" className="h-12 flex items-center gap-2 rounded-full border border-line px-5 text-[14px] lg:text-[15px] hover:bg-soft">
          <IndianRupee size={17} /><span className="font-medium">{acc ? inr(acc.balance).replace("₹", "") : "0.00"}</span>
        </Link>
        <Link to="/profile" aria-label="Profile" title={user?.email} className="icon-btn"><User size={22} strokeWidth={1.6} /></Link>
      </header>
    </>
  );
}

interface Ann { id: number; title: string; body: string; level: string }

/** Read-only "view as" banner + active announcements from the admin console (dismissed per browser). */
function TopBanners() {
  const { user, logout } = useAuth();
  const [anns, setAnns] = useState<Ann[]>([]);
  const [hidden, setHidden] = useState<number[]>(() => { try { return JSON.parse(localStorage.getItem("agt_ann_hidden") ?? "[]"); } catch { return []; } });
  useEffect(() => {
    const load = () => api<Ann[]>("/api/announcements").then(setAnns).catch(() => {});
    load();
    const id = setInterval(load, 120000);
    return () => clearInterval(id);
  }, []);
  const hide = (id: number) => { const n = [...hidden, id]; setHidden(n); try { localStorage.setItem("agt_ann_hidden", JSON.stringify(n)); } catch { /* ignore */ } };
  const tone: Record<string, string> = { warning: "bg-peach text-[#7a4a00]", success: "bg-buybg text-buy", info: "bg-[#e6f0ff] text-[#1f4fa8]" };
  return (
    <>
      {user?.read_only && (
        <div className="sticky top-0 z-[45] bg-sell text-white text-[13.5px] px-4 py-2 flex items-center gap-3 lg:pl-[264px]">
          <span className="flex-1">Viewing as <b>{user.name}</b> ({user.email}) · read-only, nothing can be changed</span>
          <button onClick={logout} className="rounded-full bg-white/20 px-3 py-1">Exit</button>
        </div>)}
      {anns.filter((a) => !hidden.includes(a.id)).map((a) => (
        <div key={a.id} className={`lg:ml-[248px] px-4 lg:px-8 py-2.5 text-[13.5px] flex items-start gap-3 ${tone[a.level] ?? tone.info}`}>
          <span className="flex-1"><b className="font-semibold">{a.title}</b>{a.body ? ` · ${a.body}` : ""}</span>
          <button aria-label="Dismiss" onClick={() => hide(a.id)} className="opacity-70 hover:opacity-100">✕</button>
        </div>))}
    </>
  );
}

export default function AppLayout() {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  // like the reference app: the stock page and the profile page cover the bottom bar
  const immersive = (pathname === "/trade" && params.get("symbol")) || pathname === "/profile";
  return (
    <div className="min-h-full bg-white">
      <DesktopChrome />
      <div className="lg:pt-[76px]"><TopBanners /></div>
      <main className={`lg:pl-[248px] ${immersive ? "pb-0" : "pb-[calc(62px+env(safe-area-inset-bottom))]"} lg:pb-10`}>
        {!immersive && <MarketBar />}
        <div key={pathname} className="lg:max-w-[1120px] lg:mx-auto lg:px-8 lg:py-6 animate-fade">
          <Outlet />
        </div>
      </main>
      {!immersive && <BottomNav />}
      <SearchOverlay />
      <NotificationCenter />
    </div>
  );
}
