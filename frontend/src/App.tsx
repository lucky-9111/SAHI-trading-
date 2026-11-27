import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import AppLayout from "./layouts/AppLayout";
import { NAV } from "./layouts/nav";
import ComingSoonPage from "./pages/ComingSoonPage";
import FundsPage from "./pages/FundsPage";
import HomePage from "./pages/HomePage";
import WatchlistPage from "./pages/WatchlistPage";
import LoginPage from "./pages/LoginPage";
import OrderBookPage from "./pages/OrderBookPage";
import PositionsPage from "./pages/PositionsPage";
import SettingsPage from "./pages/SettingsPage";
import TradeBookPage from "./pages/TradeBookPage";
import TradePage from "./pages/TradePage";

const BUILT: Record<string, ReactElement> = {
  "/": <HomePage />,
  "/watchlist": <WatchlistPage />,
  "/trade": <TradePage />,
  "/positions": <PositionsPage />,
  "/order-book": <OrderBookPage />,
  "/trade-book": <TradeBookPage />,
  "/funds": <FundsPage />,
  "/settings": <SettingsPage />,
};

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-6 text-muted">Loading…</div>;
  if (!user) return <LoginPage />;
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {NAV.map((n) => (
          <Route key={n.path} path={n.path} element={BUILT[n.path] ?? <ComingSoonPage />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
