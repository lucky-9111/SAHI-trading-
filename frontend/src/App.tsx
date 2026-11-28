import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import AppLayout from "./layouts/AppLayout";
import ComingSoonPage from "./pages/ComingSoonPage";
import FundsPage from "./pages/FundsPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import OrderBookPage from "./pages/OrderBookPage";
import PositionsPage from "./pages/PositionsPage";
import ProfilePage from "./pages/ProfilePage";
import SettingsPage from "./pages/SettingsPage";
import TradeBookPage from "./pages/TradeBookPage";
import TradePage from "./pages/TradePage";
import WatchlistPage from "./pages/WatchlistPage";

const ConsoleApp = lazy(() => import("./console/ConsoleApp"));
const spinner = <div className="h-full grid place-items-center"><div className="h-10 w-10 rounded-full border-2 border-line border-t-ink animate-spin" /></div>;

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="h-full grid place-items-center"><div className="h-10 w-10 rounded-full border-2 border-line border-t-ink animate-spin" /></div>;
  if (!user) return <LoginPage />;
  return (
    <Routes>
      <Route path="/admin/*" element={<Suspense fallback={spinner}><ConsoleApp kind="admin" /></Suspense>} />
      <Route path="/dev/*" element={<Suspense fallback={spinner}><ConsoleApp kind="dev" /></Suspense>} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/trade" element={<TradePage />} />
        <Route path="/order-book" element={<OrderBookPage />} />
        <Route path="/positions" element={<PositionsPage />} />
        <Route path="/trade-book" element={<TradeBookPage />} />
        <Route path="/funds" element={<FundsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        {["/analytics", "/journal", "/reports", "/scanner-import"].map((p) => <Route key={p} path={p} element={<ComingSoonPage />} />)}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
