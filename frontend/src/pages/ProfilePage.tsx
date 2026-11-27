import { CalendarDays, ChevronRight, FileText, History, IndianRupee, LogOut, Settings, ShieldCheck, Target, Wallet, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BackBar } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { inr } from "../utils/format";

function Tile({ to, icon, title, sub }: { to: string; icon: ReactNode; title: ReactNode; sub: string }) {
  return (
    <Link to={to} className="card flex flex-col items-center justify-center text-center px-2 py-6 press">
      <div className="mb-3">{icon}</div>
      <div className="text-[17px] lg:text-[16px] leading-tight">{title}</div>
      <div className="text-[14px] lg:text-[13px] text-muted mt-1.5">{sub}</div>
    </Link>
  );
}

function Item({ to, Icon, title, sub, danger, onClick }: { to?: string; Icon: LucideIcon; title: string; sub?: string; danger?: boolean; onClick?: () => void }) {
  const body = (
    <div className={`flex items-center gap-5 px-5 py-[18px] ${danger ? "text-sell" : ""}`}>
      <Icon size={26} strokeWidth={1.6} className="shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[17px] lg:text-[16px]">{title}</div>
        {sub && <div className="text-[14.5px] lg:text-[14px] text-muted mt-0.5 leading-snug">{sub}</div>}
      </div>
      <ChevronRight size={22} strokeWidth={1.6} className="text-[#444] shrink-0" />
    </div>
  );
  return onClick
    ? <button onClick={onClick} className="w-full text-left active:bg-soft transition-colors">{body}</button>
    : <Link to={to ?? "#"} className="block active:bg-soft transition-colors">{body}</Link>;
}

function Group({ children }: { children: ReactNode }) {
  return <div className="card overflow-hidden divide-y divide-line [&>*]:mx-0">{children}</div>;
}

export default function ProfilePage() {
  const { user, accounts, accountId, logout } = useAuth();
  const acc = accounts.find((a) => a.id === accountId);
  return (
    <div className="lg:max-w-[640px] lg:mx-auto pb-10">
      <div className="lg:hidden"><BackBar right={<Link to="/settings" aria-label="Settings" className="h-10 w-10 grid place-items-center"><Settings size={26} strokeWidth={1.6} /></Link>} /></div>
      <div className="flex flex-col items-center pt-4 lg:pt-2">
        <div className="h-[96px] w-[96px] rounded-full border-[2.5px] border-line grid place-items-center font-serif text-[44px]">{user?.name?.[0]?.toUpperCase()}</div>
        <div className="mt-4 text-[25px] font-medium">{user?.name}</div>
        <Link to="/settings" className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-panel2 px-4 py-1.5 text-[16px] press">Account details <ChevronRight size={17} /></Link>
      </div>

      <div className="grid grid-cols-3 gap-3 px-4 lg:px-0 mt-9">
        <Tile to="/funds" icon={<IndianRupee size={30} strokeWidth={1.6} />} title={acc ? inr(acc.balance) : "₹0.00"} sub="Funds" />
        <Tile to="/trade-book" icon={<History size={30} strokeWidth={1.6} />} title="Trades" sub="Trade history" />
        <Tile to="/trade-book" icon={<CalendarDays size={30} strokeWidth={1.6} />} title="P&L" sub="Daily / Monthly" />
      </div>

      <div className="px-4 lg:px-0 mt-9 space-y-6">
        <div>
          <div className="text-[18px] text-muted mb-3 px-2">Trader’s controls</div>
          <Group>
            <Item to="/settings" Icon={ShieldCheck} title="Risk protection" sub="Daily / weekly loss limits and max open positions" />
            <Item to="/positions" Icon={Target} title="P&L and positions" sub="Stop loss and target on open positions" />
            <Item to="/settings" Icon={Settings} title="Portfolios" sub="Virtual portfolios and starting capital" />
          </Group>
        </div>
        <Group>
          <Item to="/funds" Icon={Wallet} title="Funds ledger" sub="Deposits, withdrawals, every fill" />
          <Item to="/trade-book" Icon={FileText} title="Statements" sub="Trade history with charges and net P&L" />
        </Group>
        <Group>
          <Item Icon={LogOut} title="Logout" danger onClick={logout} />
        </Group>
        <p className="text-center text-[13px] text-faint pt-2">SAHI Paper Trading · virtual money only · {user?.email}</p>
      </div>
    </div>
  );
}
