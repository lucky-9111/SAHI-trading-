const TOKEN_KEY = "agt_token";
const VIEW_KEY = "agt_view_token";   // an admin's read-only "view as" token: this browser tab only

const safe = <T,>(fn: () => T, fallback: T): T => { try { return fn(); } catch { return fallback; } };

export const tokenStore = {
  get: () => safe(() => sessionStorage.getItem(VIEW_KEY), null) ?? safe(() => localStorage.getItem(TOKEN_KEY), null),
  set: (t: string) => safe(() => localStorage.setItem(TOKEN_KEY, t), undefined),
  clear: () => safe(() => localStorage.removeItem(TOKEN_KEY), undefined),
  viewing: () => !!safe(() => sessionStorage.getItem(VIEW_KEY), null),
  setView: (t: string) => safe(() => sessionStorage.setItem(VIEW_KEY, t), undefined),
  clearView: () => safe(() => sessionStorage.removeItem(VIEW_KEY), undefined),
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body: unknown): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg).filter(Boolean).join("; ");
  return "Request failed";
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the backend. Is the server running?");
  }
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (body === null && res.status >= 500) throw new ApiError(res.status, "Backend is not responding. Is the server running?");
    throw new ApiError(res.status, errorMessage(body));
  }
  return body as T;
}
