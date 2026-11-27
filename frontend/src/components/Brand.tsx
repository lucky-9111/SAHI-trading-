import { TrendingUp } from "lucide-react";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-9 w-9 rounded-xl bg-slate-900 text-up grid place-items-center shrink-0"><TrendingUp size={20} /></div>
      {!compact && (
        <div className="leading-tight">
          <div className="font-semibold text-slate-900">SAHI Trading</div>
          <div className="text-[11px] text-muted">Practice · Analyze · Improve</div>
        </div>
      )}
    </div>
  );
}
