import { useLocation } from "react-router-dom";
import { ChartArt } from "../components/art";
import { BackBar, EmptyState, PageTitle } from "../components/ui";

const NAMES: Record<string, string> = { "/analytics": "Analytics", "/journal": "Trading journal", "/reports": "Reports", "/scanner-import": "Scanner import" };

/** Honest stub: states clearly that the module is NOT built yet. */
export default function ComingSoonPage() {
  const { pathname } = useLocation();
  return (
    <div className="lg:max-w-[640px]">
      <div className="lg:hidden"><BackBar /></div>
      <PageTitle>{NAMES[pathname] ?? "Page"}</PageTitle>
      <EmptyState art={<ChartArt />} title="Not built yet" text="This module is planned for a later phase." />
    </div>
  );
}
