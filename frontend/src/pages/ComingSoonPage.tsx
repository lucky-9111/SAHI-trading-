import { useLocation } from "react-router-dom";
import { NAV } from "../layouts/nav";

/** Honest stub: states clearly that the module is NOT built yet. */
export default function ComingSoonPage() {
  const { pathname } = useLocation();
  const item = NAV.find((n) => n.path === pathname);
  return (
    <div className="panel p-8 max-w-lg">
      <h1 className="text-lg font-semibold">{item?.label ?? "Page"}</h1>
      <p className="mt-2 text-sm text-muted">
        Not implemented yet. This module is scheduled for Phase {item?.phase ?? "?"} of the build plan.
      </p>
    </div>
  );
}
