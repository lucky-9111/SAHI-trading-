import CreateAccount from "../components/CreateAccount";
import { useAuth } from "../contexts/AuthContext";
import { inr } from "../utils/format";

export default function SettingsPage() {
  const { accounts, user } = useAuth();
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Settings</h1>
      <div className="panel p-4 text-sm">
        <div className="text-muted text-xs">Signed in as</div>{user?.name} · {user?.email}
      </div>
      <div className="panel p-4">
        <h2 className="font-medium mb-2">Virtual portfolios</h2>
        <ul className="text-sm divide-y divide-line">
          {accounts.map((a) => (
            <li key={a.id} className="py-2 flex justify-between"><span>{a.name}</span><span>{inr(a.balance)}</span></li>
          ))}
        </ul>
      </div>
      <CreateAccount />
    </div>
  );
}
