import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import { inr, pnlClass } from "../utils/format";
import { Badge, Bars, Btn, ErrorBox, Page, Panel, Stat, Table, downloadCsv, statusLabel, usePoll, when } from "./kit";

/* ------------------------------------------------------------------------------------------------ overview */
interface Overview {
  stats: { online: number; active: number; disabled: number; open_positions: number; working_orders: number; unrealized: string };
  attention: { title: string; detail: string; status: string }[];
  system: { status: string; checks: { key: string; title: string; status: string; detail: string }[] };
  signins: { day: string; people: number; failed: number }[];
  policy: [string, string][];
}

export function AdminOverview() {
  const { data, error } = usePoll<Overview>("/api/admin/overview", 15000);
  const { user } = useAuth();
  return (
    <Page title="Admin overview" right={<Link to="/admin/users" className="btn-primary !rounded-full px-5 py-2.5">Manage users</Link>}>
      <ErrorBox text={error} />
      {data && <>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <Stat label="Online now" value={data.stats.online} />
          <Stat label="Active users" value={data.stats.active} />
          <Stat label="Disabled" value={data.stats.disabled} />
          <Stat label="Open positions" value={data.stats.open_positions} />
          <Stat label="Working orders" value={data.stats.working_orders} />
          <Stat label="Unrealized (all users)" value={inr(data.stats.unrealized)} tone={pnlClass(data.stats.unrealized)} />
        </div>
        <div className="grid lg:grid-cols-2 gap-4">
          <Panel title={<>Needs attention <span className="text-muted font-normal">{data.attention.length}</span></>}>
            {data.attention.length === 0 ? <div className="py-10 text-center text-muted">Nothing needs attention.</div> : (
              <ul className="divide-y divide-line">{data.attention.map((a, i) => (
                <li key={i} className="py-2.5 flex items-start gap-3"><Badge tone={a.status}>{statusLabel(a.status)}</Badge>
                  <div><div className="text-[14px] font-medium">{a.title}</div><div className="text-[13px] text-muted">{a.detail}</div></div></li>))}
              </ul>)}
          </Panel>
          <Panel title={<>System <Badge tone={data.system.status}>{statusLabel(data.system.status)}</Badge></>}
                 right={user?.role === "developer" ? <Link to="/dev" className="text-[13px] rounded-full border border-line px-3 py-1.5 hover:bg-soft">Developer console →</Link> : null}>
            <ul className="divide-y divide-line">{data.system.checks.map((c) => (
              <li key={c.key} className="py-2.5 flex items-center gap-3 text-[14px]"><span className="flex-1">{c.title}</span>
                <Badge tone={c.status}>{statusLabel(c.status)}</Badge><span className="text-muted text-[13px] text-right max-w-[60%]">{c.detail}</span></li>))}
            </ul>
          </Panel>
          <Panel title={<>People signing in <span className="text-muted font-normal text-[13px]">last 30 days</span></>}>
            <Bars values={data.signins.map((d) => d.people)} color="#7c5cff" labels={[data.signins[0]?.day ?? "", `today · ${data.signins.at(-1)?.people ?? 0} people`]} />
          </Panel>
          <Panel title={<>Failed sign-ins <span className="text-muted font-normal text-[13px]">last 30 days</span></>}>
            <Bars values={data.signins.map((d) => d.failed)} color="#d33a3a" labels={[data.signins[0]?.day ?? "", `total ${data.signins.reduce((a, d) => a + d.failed, 0)}`]} />
          </Panel>
        </div>
        <Panel title="Security policy">
          {data.policy.map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-2 border-t border-line first:border-0 text-[14px]"><span className="text-muted">{k}</span><span className="text-right">{v}</span></div>)}
        </Panel>
      </>}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ users */
interface UserRow {
  id: number; name: string; email: string; role: string; is_owner: boolean; is_active: boolean; online: boolean; device: string | null;
  last_seen: string | null; accounts: number; balance: string; open_positions: number; working_orders: number; unrealized: string;
  unrealized_partial: boolean; realized: string; can_manage: boolean; can_view_as: boolean;
}

export function AdminUsers() {
  const { data, error, reload } = usePoll<{ users: UserRow[]; assignable_roles: string[]; signup_open: boolean }>("/api/admin/users", 20000);
  const [form, setForm] = useState({ name: "", email: "", role: "user" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<string | void>) => {
    setMsg(null);
    try { const t = await fn(); if (t) setMsg({ ok: true, text: t }); await reload(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const confirmRun = (q: string, fn: () => Promise<string | void>) => { if (window.confirm(q)) run(fn); };
  const add = () => run(async () => {
    const r = await api<{ email: string; temporary_password: string }>("/api/admin/users", { method: "POST", json: form });
    setForm({ name: "", email: "", role: "user" });
    return `Added ${r.email}. Temporary password: ${r.temporary_password} (shown once; ask them to change it in Profile).`;
  });
  const viewAs = async (u: UserRow) => {
    try {
      const r = await api<{ token: string }>(`/api/admin/users/${u.id}/view-as`, { method: "POST" });
      window.open(`/?view_token=${encodeURIComponent(r.token)}`, "_blank");
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const online = data?.users.filter((u) => u.online).length ?? 0;
  return (
    <Page title="Users" badge={data && <span className="text-[12.5px] text-muted rounded-full border border-line px-2.5 py-1">{online} online · {data.users.length} total</span>}
          right={data && <Btn onClick={() => downloadCsv("sahi-users.csv", [["id", "name", "email", "role", "active", "online", "open positions", "unrealized", "realized"],
            ...data.users.map((u) => [u.id, u.name, u.email, u.role, u.is_active, u.online, u.open_positions, u.unrealized, u.realized])])}>Export CSV</Btn>}
          sub={data && (data.signup_open ? "Anyone can sign up on the sign-in page (Developer console → Switches to close it). You can also add people here." : "Sign-up is closed: you add and remove people here.")}>
      <ErrorBox text={error} />
      {msg && <div role="status" className={`rounded-2xl px-4 py-3 text-[14px] break-words ${msg.ok ? "bg-buybg/70 text-buy" : "bg-sellbg/70 text-sell"}`}>{msg.text}</div>}
      <Panel>
        <div className="flex flex-wrap items-end gap-3 pt-3">
          <label className="text-[12px] text-muted uppercase tracking-wide">Full name<input className="input mt-1 !w-[220px]" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Rahul Sharma" /></label>
          <label className="text-[12px] text-muted uppercase tracking-wide">Email<input className="input mt-1 !w-[260px]" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="rahul@example.com" /></label>
          <label className="text-[12px] text-muted uppercase tracking-wide">Role<select className="input mt-1 !w-[140px]" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {(data?.assignable_roles ?? ["user"]).map((r) => <option key={r}>{r}</option>)}</select></label>
          <button className="btn-primary !rounded-full px-5 py-3" disabled={!form.name || !form.email} onClick={add}>Add user</button>
        </div>
      </Panel>
      <Panel pad={false}>
        <div className="px-5 py-2">
          <Table head={["Name", "Role", "Status", "Online", "Device", "Portfolios", "Open", "Unrealized", "Realized", ""]}>
            {data?.users.map((u) => (
              <tr key={u.id}>
                <td><div className="font-medium">{u.name}</div><div className="text-muted text-[12.5px]">{u.email}</div></td>
                <td>{u.can_manage && data.assignable_roles.length > 1 ? (
                  <select className="rounded-lg border border-line px-2 py-1 bg-white" value={u.role}
                          onChange={(e) => confirmRun(`Make ${u.name} a ${e.target.value}?`, () => api(`/api/admin/users/${u.id}`, { method: "PATCH", json: { role: e.target.value } }).then(() => `${u.name} is now a ${e.target.value}`))}>
                    {Array.from(new Set([u.role, ...data.assignable_roles])).map((r) => <option key={r}>{r}</option>)}
                  </select>) : <span>{u.role}{u.is_owner ? " · owner" : ""}</span>}</td>
                <td><Badge tone={u.is_active ? "ok" : "fail"}>{u.is_active ? "Active" : "Disabled"}</Badge></td>
                <td>{u.online ? <span className="text-up">● online</span> : <span className="text-muted">offline</span>}</td>
                <td className="text-muted whitespace-nowrap">{u.device ?? "—"}</td>
                <td>{u.accounts} · {inr(u.balance)}</td>
                <td>{u.open_positions}{u.working_orders ? <span className="text-muted"> · {u.working_orders} orders</span> : null}</td>
                <td className={pnlClass(u.unrealized)}>{inr(u.unrealized, true)}{u.unrealized_partial ? <span className="text-faint" title="Some prices unavailable">*</span> : null}</td>
                <td className={pnlClass(u.realized)}>{inr(u.realized, true)}</td>
                <td>{u.can_manage && (
                  <div className="flex flex-wrap gap-1.5 justify-end min-w-[300px]">
                    {u.can_view_as && <Btn tone="primary" onClick={() => viewAs(u)}>View as user</Btn>}
                    <Btn onClick={() => confirmRun(`Sign ${u.name} out of every device?`, () => api<{ sessions_ended: number }>(`/api/admin/users/${u.id}/signout`, { method: "POST" }).then((r) => `${r.sessions_ended} session(s) ended`))}>Sign out</Btn>
                    <Btn onClick={() => confirmRun(`Reset ${u.name}'s password?`, () => api<{ temporary_password: string }>(`/api/admin/users/${u.id}/reset-password`, { method: "POST" }).then((r) => `New temporary password for ${u.email}: ${r.temporary_password} (shown once)`))}>Reset password</Btn>
                    <Btn onClick={() => confirmRun(`${u.is_active ? "Disable" : "Enable"} ${u.name}?`, () => api(`/api/admin/users/${u.id}`, { method: "PATCH", json: { is_active: !u.is_active } }).then(() => `${u.name} ${u.is_active ? "disabled" : "enabled"}`))}>{u.is_active ? "Disable" : "Enable"}</Btn>
                    <Btn tone="danger" onClick={() => confirmRun(`Remove ${u.name}? Their portfolios, orders and trades are deleted. This cannot be undone.`, () => api(`/api/admin/users/${u.id}`, { method: "DELETE" }).then(() => `${u.name} removed`))}>Remove</Btn>
                  </div>)}</td>
              </tr>
            ))}
          </Table>
        </div>
      </Panel>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ audit log */
interface AuditRow { id: number; ts: string; action: string; actor: string; target: string; detail: Record<string, unknown> | null }

export function AdminAudit() {
  const [q, setQ] = useState("");
  const { data, error } = usePoll<{ intact: boolean; rows_checked: number; broken_at: number | null; items: AuditRow[] }>(`/api/admin/audit?q=${encodeURIComponent(q)}`, 20000);
  return (
    <Page title="Audit log" badge={data && <Badge tone={data.intact ? "ok" : "fail"}>{data.intact ? "hash chain intact" : `broken at row ${data.broken_at}`}</Badge>}
          right={<div className="flex gap-2">
            {data && <Btn onClick={() => downloadCsv("sahi-audit.csv", [["#", "time", "action", "by", "target", "detail"], ...data.items.map((r) => [r.id, r.ts, r.action, r.actor, r.target, r.detail ? JSON.stringify(r.detail) : ""])])}>Export CSV</Btn>}
            <input className="input !w-[280px] !py-2" placeholder="Filter: login, user.disable, dev.switch …" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>}
          sub="Append-only: the database itself refuses to change or remove a row, and each row carries a hash of the one before it.">
      <ErrorBox text={error} />
      <Panel pad={false}><div className="px-5 py-2">
        <Table head={["#", "Time (IST)", "Action", "By", "Target", "Detail"]}>
          {data?.items.map((r) => (
            <tr key={r.id}>
              <td className="text-muted">{r.id}</td><td className="whitespace-nowrap">{when(r.ts)}</td>
              <td><span className={`rounded-md px-2 py-0.5 text-[12px] font-medium ${r.action.startsWith("dev.") ? "bg-[#fff1d6] text-[#8a5a00]" : "bg-soft"}`}>{r.action}</span></td>
              <td>{r.actor}</td><td className="text-muted">{r.target || "—"}</td>
              <td className="text-[12.5px] text-muted font-mono break-all max-w-[420px]">{r.detail ? JSON.stringify(r.detail) : ""}</td>
            </tr>))}
        </Table>
      </div></Panel>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ announcements */
interface Ann { id: number; title: string; body: string; level: string; active: boolean; created_by: string; created_at: string }

export function AdminAnnouncements() {
  const { data, error, reload } = usePoll<Ann[]>("/api/admin/announcements");
  const [f, setF] = useState({ title: "", body: "", level: "info" });
  const [err, setErr] = useState("");
  const call = (p: Promise<unknown>) => p.then(() => reload()).catch((e) => setErr(e.message));
  return (
    <Page title="Announcements" sub="Active announcements show as a banner at the top of the trading app for everyone.">
      <ErrorBox text={error || err} />
      <Panel title="New announcement">
        <div className="grid gap-3 pt-2 max-w-[720px]">
          <input className="input" placeholder="Title, e.g. Market holiday on Monday" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <textarea className="input min-h-[80px]" placeholder="Details (optional)" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
          <div className="flex gap-3 items-center">
            <select className="input !w-[160px]" value={f.level} onChange={(e) => setF({ ...f, level: e.target.value })}><option value="info">Info</option><option value="warning">Warning</option><option value="success">Good news</option></select>
            <button className="btn-primary !rounded-full px-5 py-3" disabled={!f.title} onClick={() => call(api("/api/admin/announcements", { method: "POST", json: f }).then(() => setF({ title: "", body: "", level: "info" })))}>Publish</button>
          </div>
        </div>
      </Panel>
      <Panel title="All announcements">
        {data?.length === 0 && <div className="py-6 text-muted">None yet.</div>}
        <ul className="divide-y divide-line">{data?.map((a) => (
          <li key={a.id} className="py-3 flex flex-wrap items-start gap-3">
            <Badge tone={a.level}>{a.level}</Badge>
            <div className="flex-1 min-w-[200px]"><div className="font-medium">{a.title}</div>{a.body && <div className="text-[13.5px] text-muted">{a.body}</div>}
              <div className="text-[12px] text-faint mt-1">{a.created_by} · {when(a.created_at)}</div></div>
            <Badge tone={a.active ? "ok" : "muted"}>{a.active ? "Showing" : "Hidden"}</Badge>
            <Btn onClick={() => call(api(`/api/admin/announcements/${a.id}`, { method: "PUT", json: { ...a, active: !a.active } }))}>{a.active ? "Hide" : "Show"}</Btn>
            <Btn tone="danger" onClick={() => window.confirm("Delete this announcement?") && call(api(`/api/admin/announcements/${a.id}`, { method: "DELETE" }))}>Delete</Btn>
          </li>))}</ul>
      </Panel>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ market calendar */
interface CalRow { date: string; exchange: string; kind: string; start: string | null; end: string | null; note: string }
interface MStatus { exchange: string; label: string; is_open: boolean; next_open: string | null }

export function AdminCalendar() {
  const { data, error, reload } = usePoll<{ entries: CalRow[]; status: MStatus[] }>("/api/admin/calendar");
  const [f, setF] = useState({ date: "", exchange: "NSE", kind: "holiday", start: "", end: "", note: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = (p: Promise<string>) => p.then((t) => { setMsg({ ok: true, text: t }); reload(); }).catch((e) => setMsg({ ok: false, text: e.message }));
  const kinds: Record<string, string> = { holiday: "Holiday (closed all day)", special: "Special session (e.g. Muhurat)", late_open: "Late open" };
  return (
    <Page title="Market calendar" right={<Btn onClick={() => run(api<{ holidays: number }>("/api/admin/calendar/sync-nse", { method: "POST" }).then((r) => `${r.holidays} NSE holidays stored`))}>Sync NSE holidays</Btn>}
          sub="Weekends are always closed. Add exchange holidays and special sessions here; the order engine reads this within a minute. A holiday missing here is treated as a trading day.">
      <ErrorBox text={error} />
      {msg && <div role="status" className={`rounded-2xl px-4 py-3 text-[14px] ${msg.ok ? "bg-buybg/70 text-buy" : "bg-sellbg/70 text-sell"}`}>{msg.text}</div>}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {data?.status.map((s) => <Stat key={s.exchange} label={s.exchange} value={<span className={`text-[16px] ${s.is_open ? "text-up" : ""}`}>{s.label}</span>} />)}
      </div>
      <Panel title="Add a day">
        <div className="flex flex-wrap items-end gap-3 pt-2">
          <label className="text-[12px] text-muted">Date<input type="date" className="input mt-1 !w-[170px]" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
          <label className="text-[12px] text-muted">Exchange<select className="input mt-1 !w-[110px]" value={f.exchange} onChange={(e) => setF({ ...f, exchange: e.target.value })}>{["NSE", "BSE", "MCX"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="text-[12px] text-muted">Type<select className="input mt-1 !w-[240px]" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          {f.kind !== "holiday" && <label className="text-[12px] text-muted">{f.kind === "late_open" ? "Opens at" : "Start"}<input type="time" className="input mt-1 !w-[120px]" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>}
          {f.kind === "special" && <label className="text-[12px] text-muted">End<input type="time" className="input mt-1 !w-[120px]" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>}
          <label className="text-[12px] text-muted flex-1 min-w-[180px]">Note<input className="input mt-1" placeholder="e.g. Christmas" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
          <button className="btn-primary !rounded-full px-5 py-3" disabled={!f.date}
                  onClick={() => run(api("/api/admin/calendar", { method: "POST", json: { ...f, start: f.start || null, end: f.end || null } }).then(() => `${f.date} saved`))}>Save</button>
        </div>
      </Panel>
      <Panel pad={false}><div className="px-5 py-2">
        <Table head={["Date", "Exchange", "Type", "Hours", "Note", ""]}>
          {data?.entries.map((r) => (
            <tr key={r.date + r.exchange}>
              <td className="whitespace-nowrap">{new Date(r.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}</td>
              <td>{r.exchange}</td><td><Badge tone={r.kind === "holiday" ? "fail" : "info"}>{r.kind.replace("_", " ")}</Badge></td>
              <td>{r.start ? `${r.start}${r.end ? `–${r.end}` : " →"}` : "closed"}</td><td className="text-muted">{r.note}</td>
              <td className="text-right"><Btn tone="danger" onClick={() => window.confirm(`Delete ${r.date} ${r.exchange}?`) && run(api(`/api/admin/calendar/${r.date}/${r.exchange}`, { method: "DELETE" }).then(() => "Deleted"))}>Delete</Btn></td>
            </tr>))}
        </Table>
        {data?.entries.length === 0 && <div className="py-6 text-muted text-center">No holidays or special sessions stored. Use “Sync NSE holidays” or add them above.</div>}
      </div></Panel>
    </Page>
  );
}
