/** Shared building blocks of the SAHI-style UI: animated underline tabs, segmented controls, chips, bottom sheet, price flash, empty state. */
import { Check, ChevronLeft, ChevronRight, Info } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { changeText, pnlClass, price as fmtPrice } from "../utils/format";

/* ---------------------------------------------------------------- underline tabs (F&O · Stocks · …) */
export function Tabs<T extends string>({ items, value, onChange, size = "lg", className = "", right }: {
  items: { value: T; label: ReactNode; info?: boolean }[]; value: T; onChange: (v: T) => void; size?: "lg" | "md"; className?: string; right?: ReactNode;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [bar, setBar] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const el = refs.current[value];
    if (!el || !wrap.current) return;
    setBar({ left: el.offsetLeft, width: el.offsetWidth });
    el.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }, [value, items.length]);
  useEffect(() => {
    const onResize = () => { const el = refs.current[value]; if (el) setBar({ left: el.offsetLeft, width: el.offsetWidth }); };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [value]);

  const text = size === "lg" ? "text-[19px] lg:text-[17px]" : "text-[17px] lg:text-[16px]";
  return (
    <div className={`relative flex items-stretch border-b border-line ${className}`}>
      <div ref={wrap} role="tablist" className="relative flex-1 flex gap-7 overflow-x-auto no-scrollbar px-4 lg:px-0">
        {items.map((it) => (
          <button key={it.value} ref={(el) => { refs.current[it.value] = el; }} role="tab" aria-selected={value === it.value}
                  onClick={() => onChange(it.value)}
                  className={`relative shrink-0 py-3.5 ${text} whitespace-nowrap transition-colors duration-200 flex items-center gap-1.5 ${
                    value === it.value ? "text-ink font-medium" : "text-muted"}`}>
            {it.label}{it.info && <Info size={16} strokeWidth={1.8} />}
          </button>
        ))}
        {bar && <span className="absolute bottom-0 h-[3px] rounded-full bg-ink transition-all duration-300 ease-[cubic-bezier(.2,.8,.2,1)]"
                      style={{ left: bar.left, width: bar.width }} />}
      </div>
      {right}
    </div>
  );
}

/* ---------------------------------------------------------------- segmented control */
/** dark: black active pill with white text (Holdings / Positions, Delivery / Intraday, Bullish / Bearish).
 *  light: white active pill with black text (Market / Limit / Trigger, Day / GTT). */
export function Segmented<T extends string>({ items, value, onChange, tone = "dark", label, disabled = [], className = "", size = "md" }: {
  items: [T, ReactNode][]; value: T; onChange: (v: T) => void; tone?: "dark" | "light"; label?: string; disabled?: T[]; className?: string; size?: "md" | "sm";
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);
  useLayoutEffect(() => {
    const el = refs.current[value];
    if (el) setPill({ left: el.offsetLeft, width: el.offsetWidth });
  }, [value, items.length]);
  const pad = size === "sm" ? "px-4 py-[6px] text-[15px]" : "px-5 py-[7px] text-[16.5px]";
  return (
    <div ref={wrap} role="group" aria-label={label} className={`seg ${className}`}>
      {pill && <span className={`absolute top-1 bottom-1 rounded-full transition-all duration-300 ease-[cubic-bezier(.2,.8,.2,1)] ${
        tone === "dark" ? "bg-ink" : "bg-white shadow-[0_1px_2px_rgba(0,0,0,.08)]"}`} style={{ left: pill.left, width: pill.width }} />}
      {items.map(([v, l]) => {
        const off = disabled.includes(v);
        const on = value === v;
        return (
          <button key={v} ref={(el) => { refs.current[v] = el; }} type="button" aria-pressed={on} disabled={off}
                  onClick={() => onChange(v)}
                  className={`relative z-10 rounded-full whitespace-nowrap transition-colors duration-200 flex items-center gap-1.5 ${pad} ${
                    on ? (tone === "dark" ? "text-white font-medium" : "text-ink font-medium") : off ? "text-faint" : "text-ink/80"}`}>
            {l}
          </button>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- chips */
export function Chip({ on, children, onClick, dot }: { on?: boolean; children: ReactNode; onClick?: () => void; dot?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={on ? "chip-on" : "chip"}>
      {dot && <span className="h-2.5 w-2.5 rounded-full bg-down" />}
      {children}{on && <Check size={17} strokeWidth={2} />}
    </button>
  );
}

/* ---------------------------------------------------------------- price that flashes on change */
export function Flash({ value, children, className = "" }: { value: number | string | null | undefined; children: ReactNode; className?: string }) {
  const prev = useRef(value);
  const [cls, setCls] = useState("");
  useEffect(() => {
    const a = Number(prev.current), b = Number(value);
    if (prev.current != null && value != null && a !== b && !Number.isNaN(a) && !Number.isNaN(b)) {
      setCls(b > a ? "animate-flashUp" : "animate-flashDown");
      const t = setTimeout(() => setCls(""), 900);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value]);
  return <span className={`rounded-md -mx-1 px-1 ${cls} ${className}`}>{children}</span>;
}

/** Price + "+65.25 (0.25%)" on two lines, right aligned, with a flash on every live change. */
export function PriceCell({ ltp, change, pct }: { ltp: string | number | null | undefined; change: string | number | null | undefined; pct: string | number | null | undefined }) {
  return (
    <div className="text-right shrink-0">
      <div className="row-price"><Flash value={ltp}>{fmtPrice(ltp)}</Flash></div>
      <div className={`row-chg ${change != null && change !== "" ? pnlClass(change) : "text-muted"}`}>{changeText(change, pct)}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- page chrome */
export function PageTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3 px-4 lg:px-0 pt-5 lg:pt-2 pb-4">
      <h1 className="page-title">{children}</h1>
      {right}
    </div>
  );
}

export function BackBar({ right, title }: { right?: ReactNode; title?: ReactNode }) {
  const nav = useNavigate();
  return (
    <div className="sticky top-0 z-20 bg-white/95 backdrop-blur flex items-center justify-between px-3 h-14">
      <button aria-label="Back" className="h-10 w-10 grid place-items-center rounded-full active:bg-soft" onClick={() => (history.length > 1 ? nav(-1) : nav("/"))}>
        <ChevronLeft size={28} strokeWidth={1.8} />
      </button>
      {title && <div className="flex-1 min-w-0 px-1">{title}</div>}
      <div className="flex items-center gap-1">{right}</div>
    </div>
  );
}

export function SectionHeader({ title, right }: { title: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-4">
      <h2 className="h2">{title}</h2>
      {right}
    </div>
  );
}

export function ViewAll({ onClick, label = "View all" }: { onClick?: () => void; label?: string }) {
  return (
    <button onClick={onClick} className="w-full flex items-center justify-between py-4 text-[17px] text-muted active:opacity-60">
      {label}<ChevronRight size={20} strokeWidth={1.6} />
    </button>
  );
}

export function EmptyState({ art, title, text, action }: { art: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center px-6 pt-10 pb-16 animate-fade">
      <div className="w-[260px] max-w-[70vw]">{art}</div>
      <div className="mt-8 text-[17px] text-muted">{title}</div>
      {text && <div className="mt-1 text-[17px] text-ink">{text}</div>}
      {action && <div className="mt-7">{action}</div>}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-5 py-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex justify-between gap-6">
          <div className="space-y-2 flex-1"><div className="skeleton h-4 w-2/5" /><div className="skeleton h-3 w-1/6" /></div>
          <div className="space-y-2 w-24"><div className="skeleton h-4" /><div className="skeleton h-3" /></div>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- bottom sheet */
/** A sheet that slides up over a dimmed page on phones and sits centred on large screens. Drag the handle down (or tap outside) to close. */
export function Sheet({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label?: string }) {
  const [dy, setDy] = useState(0);
  const start = useRef<number | null>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; window.removeEventListener("keydown", onKey); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={label}>
      <div className="absolute inset-0 bg-black/45 animate-backdrop" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 lg:inset-0 lg:grid lg:place-items-center pointer-events-none">
        <div className="pointer-events-auto bg-white rounded-t-[28px] lg:rounded-[28px] shadow-sheet animate-sheet lg:animate-fade max-h-[92vh] lg:max-h-[88vh] w-full lg:w-[440px] flex flex-col"
             style={{ transform: dy ? `translateY(${dy}px)` : undefined, transition: start.current === null ? "transform .2s" : "none" }}>
          <div className="pt-2.5 pb-1 grid place-items-center cursor-grab touch-none lg:hidden"
               onPointerDown={(e) => { start.current = e.clientY; (e.target as HTMLElement).setPointerCapture(e.pointerId); }}
               onPointerMove={(e) => { if (start.current !== null) setDy(Math.max(0, e.clientY - start.current)); }}
               onPointerUp={() => { const close = dy > 110; start.current = null; setDy(0); if (close) onClose(); }}>
            <span className="h-1.5 w-10 rounded-full bg-line" />
          </div>
          <div className="overflow-y-auto overscroll-contain">{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- switch */
export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
            className={`relative h-[32px] w-[58px] shrink-0 rounded-full border-[1.5px] transition-colors duration-200 ${on ? "bg-ink border-ink" : "bg-white border-ink"}`}>
      <span className={`absolute top-[4px] h-[21px] w-[21px] rounded-full transition-all duration-200 ${on ? "left-[30px] bg-white" : "left-[4px] bg-[#444]"}`} />
    </button>
  );
}
