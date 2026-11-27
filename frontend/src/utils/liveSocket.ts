import { useEffect, useRef, useState } from "react";
import { api, tokenStore } from "../services/api";

/** One WebSocket per browser tab to /ws/ticks. Screens subscribe to "EXCHANGE:TOKEN" keys; the server pushes at most ~4 updates per second per symbol,
 *  plus feed status (connected / stale / reconnecting / closed / replay) and "orders_changed" events. Reconnects by itself (1, 2, 4 ... 30 s). */
export interface WsTick { k: string; ltp: number; ts: number; state: string; at: number }
export type FeedState = "connected" | "stale" | "reconnecting" | "closed" | "replay" | "offline"
type Msg = { type: "tick" } & Omit<WsTick, "at"> | { type: "feed"; state: FeedState; last_tick_age_s: number | null } | { type: "orders_changed"; events?: string[] }

class LiveSocket {
  private ws: WebSocket | null = null
  private refs = new Map<string, number>()
  private tickL = new Set<(t: WsTick) => void>()
  private feedL = new Set<(s: FeedState) => void>()
  private ordersL = new Set<() => void>()
  private backoff = 1000
  feed: FeedState = "offline"
  open = false
  last = new Map<string, WsTick>()

  private url(): string | null {
    const t = tokenStore.get()
    if (!t) return null
    const proto = location.protocol === "https:" ? "wss" : "ws"
    return `${proto}://${location.host}/ws/ticks?token=${encodeURIComponent(t)}`
  }

  private connect() {
    if (this.ws || typeof WebSocket === "undefined") return
    const url = this.url()
    if (!url) return
    const ws = new WebSocket(url)
    this.ws = ws
    ws.onopen = () => {
      this.open = true
      this.backoff = 1000
      if (this.refs.size) ws.send(JSON.stringify({ op: "subscribe", symbols: [...this.refs.keys()] }))
    }
    ws.onmessage = (e) => {
      let m: Msg
      try { m = JSON.parse(e.data) } catch { return }
      if (m.type === "tick") {
        const t = { ...m, at: Date.now() } as WsTick
        this.last.set(t.k, t)
        this.tickL.forEach((f) => f(t))
      } else if (m.type === "feed") {
        this.feed = m.state
        this.feedL.forEach((f) => f(m.state))
      } else if (m.type === "orders_changed") this.ordersL.forEach((f) => f())
    }
    ws.onclose = () => {
      this.ws = null
      this.open = false
      this.feed = "offline"
      this.feedL.forEach((f) => f("offline"))
      if (this.refs.size || this.feedL.size || this.ordersL.size) {
        setTimeout(() => this.connect(), this.backoff)
        this.backoff = Math.min(this.backoff * 2, 30000)
      }
    }
    ws.onerror = () => ws.close()
  }

  subscribe(keys: string[]): () => void {
    const fresh: string[] = []
    for (const k of keys) {
      const n = this.refs.get(k) ?? 0
      if (n === 0) fresh.push(k)
      this.refs.set(k, n + 1)
    }
    this.connect()
    if (fresh.length && this.ws && this.open) this.ws.send(JSON.stringify({ op: "subscribe", symbols: fresh }))
    return () => {
      const gone: string[] = []
      for (const k of keys) {
        const n = (this.refs.get(k) ?? 1) - 1
        if (n <= 0) { this.refs.delete(k); gone.push(k) } else this.refs.set(k, n)
      }
      if (gone.length && this.ws && this.open) this.ws.send(JSON.stringify({ op: "unsubscribe", symbols: gone }))
    }
  }

  onTick(f: (t: WsTick) => void) { this.tickL.add(f); return () => { this.tickL.delete(f) } }
  onFeed(f: (s: FeedState) => void) { this.connect(); this.feedL.add(f); return () => { this.feedL.delete(f) } }
  onOrders(f: () => void) { this.connect(); this.ordersL.add(f); return () => { this.ordersL.delete(f) } }
}

export const live = new LiveSocket()

/** The feed state the server reports ("offline" while the socket itself is down). */
export function useFeedState(): FeedState {
  const [s, setS] = useState<FeedState>(live.feed)
  useEffect(() => { setS(live.feed); return live.onFeed(setS) }, [])
  return s
}

/** Run `fn` when the server says this user's orders / positions changed (a fill, stop, target, square-off). */
export function useOrdersChanged(fn: () => void) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => live.onOrders(() => ref.current()), [])
}

interface TicksResponse { ticks: Record<string, { ltp: number; age: number; state: string }> }

/** Live price of one token: pushed over the websocket; if the socket is down it falls back to polling /api/market/ticks every 2 s. */
export function useLiveTick(exchange: string | undefined, token: string | undefined) {
  const key = exchange && token ? `${exchange}:${token}` : null
  const [tick, setTick] = useState<WsTick | null>(null)
  const feed = useFeedState()
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    setTick(null)
    if (!key) return
    const first = live.last.get(key)
    if (first) setTick(first)
    const off = live.onTick((t) => { if (t.k === key) setTick(t) })
    const un = live.subscribe([key])
    return () => { off(); un() }
  }, [key])

  // REST fallback while the websocket is not open
  useEffect(() => {
    if (!key || feed !== "offline") return
    let stop = false
    const load = () => {
      if (document.hidden) return
      api<TicksResponse>(`/api/market/ticks?s=${encodeURIComponent(key)}`).then((r) => {
        const t = r.ticks[key]
        if (t && !stop) setTick({ k: key, ltp: t.ltp, ts: 0, state: t.state, at: Date.now() - t.age * 1000 })
      }).catch(() => {})
    }
    load()
    const id = setInterval(load, 2000)
    return () => { stop = true; clearInterval(id) }
  }, [key, feed])

  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(id) }, [])
  // fresh = the server calls it live and we heard from it in the last 20 s (a quiet symbol turns grey, never invented)
  const fresh = !!tick && tick.state === "live" && now - tick.at < 20000
  return { tick: tick ? { ltp: tick.ltp, age: (now - tick.at) / 1000, state: tick.state } : null, fresh, feed }
}
