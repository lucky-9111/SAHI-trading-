import CreateAccount from "../components/CreateAccount";
import OrderSettings from "../components/OrderSettings";
import { BackBar, PageTitle } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { inr } from "../utils/format";

export default function SettingsPage() {
  const { accounts, user, accountId, setAccountId } = useAuth();
  return (
    <div className="lg:max-w-[640px]">
      <div className="lg:hidden"><BackBar /></div>
      <PageTitle>Settings</PageTitle>
      <div className="px-4 lg:px-0 space-y-6">
        <div className="card px-5 py-4">
          <div className="text-[12px] lg:text-[13px] text-muted">Signed in as</div>
          <div className="text-[16px] lg:text-[17px] mt-0.5">{user?.name}</div>
          <div className="text-[14px] lg:text-[15px] text-muted">{user?.email}</div>
        </div>
        <div>
          <div className="text-[15px] lg:text-[16px] text-muted mb-2 px-1">Virtual portfolios</div>
          <div className="card divide-y divide-line">
            {accounts.map((a) => (
              <button key={a.id} onClick={() => setAccountId(a.id)} className="w-full flex items-center justify-between px-5 py-4 text-left active:bg-soft">
                <span className="text-[16px] lg:text-[17px]">{a.name}{a.id === accountId && <span className="ml-2 text-[12px] lg:text-[13px] text-up">● active</span>}</span>
                <span className="text-[15px] lg:text-[16px]">{inr(a.balance)}</span>
              </button>
            ))}
          </div>
        </div>
        <OrderSettings />
        <CreateAccount />
      </div>
    </div>
  );
}
