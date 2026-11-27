import {
  BarChart3, BookOpen, Briefcase, ClipboardList, FileText, History, Home, LineChart, ScanSearch, Settings, Star,
  Wallet, type LucideIcon,
} from "lucide-react";

export interface NavItem { path: string; label: string; icon: LucideIcon; phase: number | null }

/** phase === null means the page is implemented. */
export const NAV: NavItem[] = [
  { path: "/", label: "Home", icon: Home, phase: null },
  { path: "/watchlist", label: "Watchlist", icon: Star, phase: null },
  { path: "/trade", label: "Trade", icon: LineChart, phase: null },
  { path: "/order-book", label: "Orders", icon: ClipboardList, phase: null },
  { path: "/positions", label: "Portfolio", icon: Briefcase, phase: null },
  { path: "/trade-book", label: "Trade History", icon: History, phase: null },
  { path: "/funds", label: "Funds", icon: Wallet, phase: null },
  { path: "/analytics", label: "Analytics", icon: BarChart3, phase: 7 },
  { path: "/journal", label: "Trading Journal", icon: BookOpen, phase: 6 },
  { path: "/reports", label: "Reports", icon: FileText, phase: 8 },
  { path: "/scanner-import", label: "Scanner Import", icon: ScanSearch, phase: 10 },
  { path: "/settings", label: "Settings", icon: Settings, phase: null },
];
