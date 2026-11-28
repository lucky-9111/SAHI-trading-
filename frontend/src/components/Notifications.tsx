import { Bell, CheckCircle2, CircleAlert, Info, TriangleAlert, X } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { istTime } from "../utils/format";
import { live, type AppNotification } from "../utils/liveSocket";
import { Sheet } from "./ui";

/** Order notifications: pushed by the backend over the websocket the moment an order changes, with a 10 s catch-up poll for missed pushes.
 *  The backend writes them in the same transaction as the order change, so a toast always describes something that really happened. */

interface State { items: AppNotification[]; unread: number; toasts: AppNotification[] }
let state: State = { items: [], unread: 0, toasts: [] };
let latest = 0;
let primed = false;
const subs = new Set<() => void>();
const set = (s: Partial<State>) => { state = { ...state, ...s }; subs.forEach((f) => f()); };
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export const useNotifications = () => useSyncExternalStore(subscribe, () => state);

const TOAST_MS = 6000;

function add(list: AppNotification[], toast: boolean) {
  const fresh = list.filter((n) => n.id > latest && !state.items.some((x) => x.id === n.id));
  if (!fresh.length) return;
  latest = Math.max(latest, ...fresh.map((n) => n.id));
  set({
    items: [...fresh.reverse(), ...state.items].slice(0, 100),
    unread: state.unread + fresh.filter((n) => !n.is_read).length,
    toasts: toast ? [...state.toasts, ...fresh].slice(-4) : state.toasts,
  });
  if (toast) fresh.forEach((n) => setTimeout(() => dismiss(n.id), TOAST_MS));
}
function dismiss(id: number) { set({ toasts: state.toasts.filter((t) => t.id !== id) }); }

async function prime() {
  const r = await api<{ items: AppNotification[]; unread: number; latest_id: number }>("/api/notifications?limit=50");
  state = { ...state, items: [...r.items].reverse(), unread: r.unread };
  latest = r.latest_id;
  primed = true;
  subs.forEach((f) => f());
}
async function catchUp() {
  if (!primed) return prime();
  const r = await api<{ items: AppNotification[] }>(`/api/notifications?after_id=${latest}`);
  add(r.items, true);
}
async function markAllRead() {
  set({ unread: 0, items: state.items.map((n) => ({ ...n, is_read: true })) });
  await api("/api/notifications/read", { method: "POST", json: {} }).catch(() => {});
}

const ICON = { success: CheckCircle2, error: CircleAlert, warning: TriangleAlert, info: Info };
const TONE = { success: "text-up", error: "text-down", warning: "text-[#b26a00]", info: "text-ink" };

/** Mount once (AppLayout): receives pushes, polls for anything missed, renders the toasts. */
export function NotificationCenter() {
  const { toasts } = useNotifications();
  const nav = useNavigate();
  useEffect(() => {
    prime().catch(() => {});
    const off = live.onNotification((n) => { if (primed) add([n], true); else catchUp().catch(() => {}); });
    const id = setInterval(() => { if (!document.hidden) catchUp().catch(() => {}); }, 10000);
    return () => { off(); clearInterval(id); };
  }, []);
  return (
    <div aria-live="polite" className="fixed z-[60] top-3 inset-x-3 lg:inset-x-auto lg:right-6 lg:top-[88px] lg:w-[380px] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => {
        const I = ICON[t.level] ?? Info;
        return (
          <div key={t.id} role="status" className="pointer-events-auto animate-fade rounded-2xl bg-white border border-line shadow-float px-4 py-3 flex items-start gap-3">
            <I size={20} className={`mt-0.5 shrink-0 ${TONE[t.level] ?? ""}`} />
            <button className="flex-1 min-w-0 text-left" onClick={() => { dismiss(t.id); if (t.order_id) nav(`/order-book?order=${t.order_id}`); }}>
              <div className="text-[14.5px] lg:text-[15px] font-medium">{t.title}</div>
              <div className="text-[13px] lg:text-[13.5px] text-muted mt-0.5 break-words">{t.body}</div>
            </button>
            <button aria-label="Dismiss" className="text-faint hover:text-ink" onClick={() => dismiss(t.id)}><X size={18} /></button>
          </div>
        );
      })}
    </div>
  );
}

/** Bell with the unread count; opens the order activity panel. */
export function NotificationBell({ className = "icon-btn" }: { className?: string }) {
  const { items, unread } = useNotifications();
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  return (
    <>
      <button aria-label={`Order activity${unread ? `, ${unread} unread` : ""}`} className={`relative ${className}`} onClick={() => { setOpen(true); if (unread) markAllRead(); }}>
        <Bell size={20} strokeWidth={1.7} />
        {unread > 0 && <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-sell text-white text-[11px] leading-[18px] text-center">{unread > 9 ? "9+" : unread}</span>}
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} label="Order activity">
        <div className="px-5 pt-2 pb-6">
          <div className="text-[19px] lg:text-[21px] mb-3">Order activity</div>
          {items.length === 0 && <div className="py-10 text-center text-muted">No order activity yet.</div>}
          <div className="divide-y divide-line">
            {items.map((n) => {
              const I = ICON[n.level] ?? Info;
              return (
                <button key={n.id} className="w-full flex items-start gap-3 py-3 text-left active:bg-soft" onClick={() => { setOpen(false); if (n.order_id) nav(`/order-book?order=${n.order_id}`); }}>
                  <I size={18} className={`mt-0.5 shrink-0 ${TONE[n.level] ?? ""}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between gap-2"><span className="text-[14.5px] font-medium">{n.title}</span>
                      <span className="text-[12px] text-faint whitespace-nowrap">{istTime(n.created_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span></div>
                    <div className="text-[13px] text-muted mt-0.5 break-words">{n.body}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </Sheet>
    </>
  );
}
