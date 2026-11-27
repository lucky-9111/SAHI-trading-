/** Hand-drawn style line art, nav icons, the app mark and commodity icons. All original SVG. */
import type { SVGProps } from "react";

const sketch = { fill: "none", stroke: "#4a4a4a", strokeWidth: 2.2, strokeLinejoin: "round" as const, strokeLinecap: "round" as const };

function Hatch({ id }: { id: string }) {
  return (
    <pattern id={id} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="7" stroke="#4a4a4a" strokeWidth="1.6" />
    </pattern>
  );
}

/** Open briefcase: the empty Portfolio. */
export function BriefcaseArt() {
  return (
    <svg viewBox="0 0 320 300" className="w-full h-auto" aria-hidden>
      <defs><Hatch id="hb" /></defs>
      <g {...sketch}>
        <path d="M60 140 L180 108 L245 168 L125 205 Z" />
        <path d="M60 140 L55 210 L120 270 L125 205" />
        <path d="M125 205 L120 270 L240 236 L245 168" />
        <path d="M120 270 L240 236 L245 168 L125 205 Z" fill="url(#hb)" opacity=".9" />
        <path d="M180 108 L215 13 L285 75 L245 168" />
        <path d="M215 13 L225 18 L292 80 L285 75" />
        <path d="M225 18 L292 80 L250 172" fill="url(#hb)" />
        <path d="M85 160 L95 195 L110 210" strokeWidth="2" />
        <path d="M90 165 L100 158 L112 196 L104 203" strokeWidth="2" />
        <path d="M40 120 L70 115 M250 250 L285 245 M20 260 L30 250 M290 120 L300 100" strokeWidth="1.2" opacity=".6" />
      </g>
    </svg>
  );
}

/** Clipboard and pencil: the empty Orders page. */
export function ClipboardArt() {
  return (
    <svg viewBox="0 0 320 300" className="w-full h-auto" aria-hidden>
      <defs><Hatch id="hc" /></defs>
      <g {...sketch}>
        <path d="M120 40 L270 75 L215 280 L65 245 Z" />
        <path d="M215 280 L65 245 L62 255 L212 292 Z" fill="url(#hc)" />
        <path d="M270 75 L280 80 L222 290 L215 280" fill="url(#hc)" />
        <path d="M135 58 L255 86 L208 262 L85 233 Z" />
        <path d="M170 35 L215 46 L208 70 L162 60 Z" />
        <circle cx="194" cy="38" r="8" />
        <path d="M200 230 Q205 205 230 205 Q215 220 200 230 Z" />
        <path d="M30 175 L150 110 L162 128 L42 192 Z" />
        <path d="M30 175 L15 190 L42 192" />
        <path d="M150 110 L165 100 L175 118 L162 128" />
        <path d="M25 160 L40 150 M285 60 L300 40 M60 270 L70 290" strokeWidth="1.2" opacity=".6" />
      </g>
    </svg>
  );
}

/** Magnifier over chart: generic "nothing here yet". */
export function ChartArt() {
  return (
    <svg viewBox="0 0 320 260" className="w-full h-auto" aria-hidden>
      <defs><Hatch id="hd" /></defs>
      <g {...sketch}>
        <path d="M40 210 L280 210" />
        <path d="M60 210 L60 150 L90 150 L90 210" fill="url(#hd)" />
        <path d="M110 210 L110 110 L140 110 L140 210" />
        <path d="M160 210 L160 130 L190 130 L190 210" fill="url(#hd)" />
        <path d="M210 210 L210 70 L240 70 L240 210" />
        <path d="M50 120 L120 80 L170 100 L250 40" />
        <circle cx="235" cy="150" r="32" fill="#fff" />
        <path d="M258 173 L290 205" strokeWidth="5" />
      </g>
    </svg>
  );
}

/* ---------------------------------------------------------------- app mark (our own, not a copy) */
export function AppMark({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-label="SAHI Trading">
      <rect x="2" y="2" width="36" height="36" rx="11" fill="#fff" stroke="#e4e4e4" />
      <path d="M11 25 L17 19 L21 22.5 L29 14" fill="none" stroke="#c2177a" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M24 14 L29 14 L29 19" fill="none" stroke="#c2177a" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ---------------------------------------------------------------- bottom-nav icons (outline / filled) */
type I = SVGProps<SVGSVGElement> & { active?: boolean };
const base = (p: I) => ({ width: 30, height: 30, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, ...p });

export function HomeIcon({ active, ...p }: I) {
  return (
    <svg {...base(p)}>
      <path d="M4.5 10.2c0-.9.4-1.7 1.1-2.2l5.2-4a2 2 0 0 1 2.4 0l5.2 4c.7.5 1.1 1.3 1.1 2.2v6.3a4 4 0 0 1-4 4h-7a4 4 0 0 1-4-4z" fill={active ? "currentColor" : "none"} />
      <path d="M9.3 14.6c1.5 1.4 3.9 1.4 5.4 0" stroke={active ? "#fff" : "currentColor"} />
    </svg>
  );
}
export function WatchIcon({ active, ...p }: I) {
  return <svg {...base(p)}><path d="M7 3.5h10a1.5 1.5 0 0 1 1.5 1.5v15.2a.5.5 0 0 1-.8.4L12 16.8l-5.7 3.8a.5.5 0 0 1-.8-.4V5A1.5 1.5 0 0 1 7 3.5z" fill={active ? "currentColor" : "none"} /></svg>;
}
export function TradeIcon({ active, ...p }: I) {
  return (
    <svg {...base({ ...p, strokeWidth: active ? 2.2 : 1.6 })}>
      <path d="M13.5 4.5H19.5V10.5" /><path d="M19.5 4.5L12 12" /><path d="M10.5 19.5H4.5V13.5" /><path d="M4.5 19.5L9 15" /><path d="M14.5 9.5l-1 1" />
    </svg>
  );
}
export function OrdersIcon({ active, ...p }: I) {
  return (
    <svg {...base(p)}>
      <path d="M6 3.5h11.5v14H7.2A1.7 1.7 0 0 0 5.5 19.2V5A1.5 1.5 0 0 1 6 3.5z" fill={active ? "currentColor" : "none"} />
      <path d="M5.5 19.2c0 .9.8 1.3 1.7 1.3h10.3v-3" />
    </svg>
  );
}
export function PortfolioIcon({ active, ...p }: I) {
  return (
    <svg {...base(p)}>
      <rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill={active ? "currentColor" : "none"} />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
      <path d="M3.5 12.5h17" stroke={active ? "#fff" : "currentColor"} /><path d="M10.5 12.5v1.5h3v-1.5" stroke={active ? "#fff" : "currentColor"} />
    </svg>
  );
}

/* ---------------------------------------------------------------- commodity icons */
function Cube({ c1, c2, c3, small }: { c1: string; c2: string; c3: string; small?: boolean }) {
  return (
    <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden>
      <g transform={small ? "translate(6 8) scale(.78)" : undefined}>
        <path d="M24 6 L42 15 L24 24 L6 15 Z" fill={c1} />
        <path d="M6 15 L24 24 L24 43 L6 34 Z" fill={c2} />
        <path d="M42 15 L24 24 L24 43 L42 34 Z" fill={c3} />
      </g>
      {small && <path d="M36 4 L44 8 L36 12 L28 8 Z M28 8 L36 12 L36 20 L28 16 Z M44 8 L36 12 L36 20 L44 16 Z" fill={c2} />}
    </svg>
  );
}
function Barrel({ small }: { small?: boolean }) {
  return (
    <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden>
      <g transform={small ? "translate(4 8) scale(.8)" : undefined}>
        <rect x="11" y="6" width="26" height="36" rx="5" fill="#c62828" />
        <rect x="11" y="6" width="9" height="36" rx="4" fill="#e53935" />
        <path d="M11 16h26M11 32h26" stroke="#8e1b1b" strokeWidth="2" />
      </g>
      {small && <rect x="36" y="4" width="8" height="12" rx="2" fill="#c62828" />}
    </svg>
  );
}
function Sphere({ small }: { small?: boolean }) {
  return (
    <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden>
      <defs><radialGradient id="sg" cx=".35" cy=".3" r=".75"><stop offset="0" stopColor="#ffffff" /><stop offset=".55" stopColor="#bdbdbd" /><stop offset="1" stopColor="#7d7d7d" /></radialGradient></defs>
      <circle cx={small ? 20 : 24} cy={small ? 28 : 24} r={small ? 13 : 17} fill="url(#sg)" />
      {small && <circle cx="37" cy="12" r="6" fill="url(#sg)" />}
    </svg>
  );
}
function Flame() {
  return <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden><path d="M24 5c3 8 12 12 12 23a12 12 0 0 1-24 0c0-6 3-9 5-12 1 4 3 6 5 6-2-6 0-12 2-17z" fill="#1e88e5" /><path d="M24 24c2 3 6 5 6 10a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3-1-3 0-5 1-7z" fill="#90caf9" /></svg>;
}
function Bar({ color }: { color: string }) {
  return <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden><path d="M8 30 L18 18 L42 18 L32 30 Z" fill={color} opacity=".75" /><path d="M8 30 L32 30 L32 36 L8 36 Z" fill={color} /><path d="M32 30 L42 18 L42 24 L32 36 Z" fill={color} opacity=".55" /></svg>;
}
function Leaf() {
  return <svg viewBox="0 0 48 48" className="h-11 w-11" aria-hidden><path d="M10 38C10 18 22 8 40 8c0 20-10 30-30 30z" fill="#43a047" /><path d="M10 38L30 18" stroke="#1b5e20" strokeWidth="2" /></svg>;
}

export function CommodityIcon({ name }: { name: string }) {
  const n = name.toUpperCase();
  if (n === "GOLDM" || n === "GOLDPETAL" || n === "GOLDGUINEA" || n === "GOLDTEN") return <Cube c1="#ffd54f" c2="#f9a825" c3="#c88a12" small />;
  if (n.startsWith("GOLD")) return <Cube c1="#ffd54f" c2="#f9a825" c3="#c88a12" />;
  if (n === "SILVERM" || n === "SILVERMIC") return <Sphere small />;
  if (n.startsWith("SILVER")) return <Sphere />;
  if (n === "CRUDEOILM") return <Barrel small />;
  if (n.startsWith("CRUDE")) return <Barrel />;
  if (n.startsWith("NATURALGAS") || n.startsWith("NATGAS")) return <Flame />;
  if (n.startsWith("COPPER")) return <Bar color="#d2691e" />;
  if (["MENTHAOIL", "COTTON", "CARDAMOM"].includes(n)) return <Leaf />;
  return <Bar color="#90a4ae" />;
}
