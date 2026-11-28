import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { Badge, Btn, ErrorBox, Page, Panel, Stat, Table, ago, statusLabel, usePoll, when } from "./kit";

/* ------------------------------------------------------------------------------------------------ system health */
interface Check { key: string; title: string; status: string; detail: string }
interface SelfTests { passed: number; failed: number; last_run_ago_s: number; results: { check: string; passed: boolean; expected: string | null; actual: string | null; ms: number }[] }

export function DevHealth() {
  const { data, error, reload, setData } = usePoll<{ status: string; checks: Check[]; checked_at: string; selftests: SelfTests }>("/api/dev/health", 5000);
  const [busy, setBusy] = useState(false);
  const rerun = async () => {
    setBusy(true);
    try { const s = await api<SelfTests>("/api/dev/selftest", { method: "POST" }); if (data) setData({ ...data, selftests: s }); await reload(); } finally { setBusy(false); }
  };
  return (
    <Page title="System health" badge={data && <Badge tone={data.status}>{statusLabel(data.status)}</Badge>} right={<span className="text-[12.5px] text-muted">refreshes every 5 s</span>}>
      <ErrorBox text={error} />
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {data?.checks.map((c) => (
          <div key={c.key} className={`card px-4 py-3 ${c.status === "fail" ? "border-sell/50" : ""}`}>
            <div className="flex items-center justify-between gap-2"><span className="font-semibold text-[14.5px]">{c.title}</span><Badge tone={c.status}>{statusLabel(c.status)}</Badge></div>
            <div className="text-[13px] text-muted mt-1.5">{c.detail}</div>
          </div>))}
      </div>
      {data && (
        <Panel title={<>Known-answer self-tests <Badge tone={data.selftests.failed ? "fail" : "ok"}>{data.selftests.passed} passed · {data.selftests.failed} failed</Badge></>}
               right={<><span className="text-[12.5px] text-muted">last run {ago(data.selftests.last_run_ago_s)}</span><Btn tone="primary" disabled={busy} onClick={rerun}>{busy ? "Running…" : "Run now"}</Btn></>}>
          <p className="text-[13px] text-muted mb-2">Each check feeds a small fixed input to a real function (charges, market status, fills, prices, log masking) and compares it with an answer worked out by hand. A failure names the function and shows the difference.</p>
          <Table head={["Check", "Result", "Expected", "Actual", "ms"]}>
            {data.selftests.results.map((r) => (
              <tr key={r.check}><td className="font-mono text-[12.5px]">{r.check}</td><td><Badge tone={r.passed ? "ok" : "fail"}>{r.passed ? "Pass" : "Fail"}</Badge></td>
                <td className="text-muted">{r.expected ?? ""}</td><td className="text-sell">{r.actual ?? ""}</td><td className="text-muted">{r.ms}</td></tr>))}
          </Table>
        </Panel>)}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ Angel One API */
interface Endpoint { endpoint: string; label: string; api: string; count: number; median_ms: number | null; p95_ms: number | null; slowest_ms: number | null; errors: number; rate_limited: number; last_ago_s: number | null; last_error: string | null; last_error_ago_s: number | null }
interface AngelData { window_s: number; calls: number; errors: number; rate_limited: number; endpoints: Endpoint[]; configured: boolean; provider: { state: string; reason: string } }

export function DevAngel() {
  const [win, setWin] = useState(3600);
  const { data, error } = usePoll<AngelData>(`/api/dev/angel?window=${win}`, 15000);
  const [probe, setProbe] = useState<{ ok: boolean; ms: number; detail: string } | null>(null);
  const ms = (v: number | null) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${v} ms`);
  return (
    <Page title="Angel One API" sub="Measured on the calls SAHI already makes (nothing extra is sent). Refreshes every 15 seconds. Resets when the server restarts.">
      <ErrorBox text={error} />
      {data && <>
        <Panel title={<>Overall <Badge tone={!data.configured ? "fail" : data.errors + data.rate_limited ? "warn" : "ok"}>{!data.configured ? "Not set up" : data.errors + data.rate_limited ? "Check" : "OK"}</Badge></>}
               right={<><select className="rounded-full border border-line px-3 py-1.5 text-[13px] bg-white" value={win} onChange={(e) => setWin(Number(e.target.value))}>
                 <option value={900}>last 15 min</option><option value={3600}>last hour</option><option value={21600}>last 6 hours</option><option value={86400}>last 24 hours</option></select>
                 <Btn onClick={() => api<{ ok: boolean; ms: number; detail: string }>("/api/dev/angel/probe", { method: "POST" }).then(setProbe).catch((e) => setProbe({ ok: false, ms: 0, detail: e.message }))}>Probe now</Btn></>}>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
            <Stat label="Calls" value={data.calls} /><Stat label="Errors" value={data.errors} tone={data.errors ? "text-sell" : ""} />
            <Stat label="Rate limited (403 / 429)" value={data.rate_limited} tone={data.rate_limited ? "text-[#b26a00]" : ""} />
            <Stat label="Broker session" value={<span className="text-[15px]">{data.provider.state}</span>} />
          </div>
          <div className="text-[13px] text-muted mt-2">{data.provider.reason}</div>
          {probe && <div className={`mt-3 rounded-xl px-3 py-2 text-[13.5px] ${probe.ok ? "bg-buybg/70 text-buy" : "bg-sellbg/70 text-sell"}`}>Probe: {probe.detail} ({probe.ms} ms)</div>}
        </Panel>
        <Panel title="By endpoint">
          <Table head={["Call", "Count", "Median", "95%", "Slowest", "Errors", "Rate limited", "Last", "Last error"]}>
            {data.endpoints.map((e) => (
              <tr key={e.endpoint}><td><div className="font-medium">{e.label}</div><div className="text-muted text-[12px]">{e.api}</div></td>
                <td>{e.count}</td><td>{ms(e.median_ms)}</td><td>{ms(e.p95_ms)}</td><td>{ms(e.slowest_ms)}</td>
                <td className={e.errors ? "text-sell" : ""}>{e.errors}</td><td>{e.rate_limited}</td><td className="text-muted">{ago(e.last_ago_s)}</td>
                <td className="text-[12.5px] text-muted max-w-[320px] break-words">{e.last_error ? `${ago(e.last_error_ago_s)} · ${e.last_error}` : "—"}</td></tr>))}
          </Table>
          {data.endpoints.length === 0 && <div className="py-6 text-center text-muted">No Angel One calls in this window.</div>}
        </Panel>
      </>}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ errors */
interface Incident { component: string; level: string; message: string; count: number; first_ago_s: number; last_ago_s: number }

export function DevErrors() {
  const { data, error } = usePoll<{ grouped: Incident[]; recent: { ago_s: number; component: string; level: string; message: string }[]; last_hour: number }>("/api/dev/errors", 10000);
  return (
    <Page title="Errors and incidents" badge={data && <Badge tone={data.last_hour ? "warn" : "ok"}>{data.last_hour} in the last hour</Badge>}
          sub="Every warning and error the backend logged since the last restart: grouped by cause first, then the latest entries. Secrets are masked.">
      <ErrorBox text={error} />
      <Panel title="Grouped by cause">
        <Table head={["Component", "Level", "Message", "Count", "First seen", "Last seen"]}>
          {data?.grouped.map((g, i) => (
            <tr key={i}><td className="font-mono text-[12.5px]">{g.component}</td><td><Badge tone={g.level === "WARNING" ? "warn" : "fail"}>{g.level}</Badge></td>
              <td className="max-w-[520px] break-words">{g.message}</td><td>{g.count}</td><td className="text-muted">{ago(g.first_ago_s)}</td><td className="text-muted">{ago(g.last_ago_s)}</td></tr>))}
        </Table>
        {data?.grouped.length === 0 && <div className="py-8 text-center text-muted">No warnings or errors since the server started.</div>}
      </Panel>
      {!!data?.recent.length && (
        <Panel title="Latest">
          <Table head={["When", "Component", "Message"]}>
            {data.recent.slice(0, 50).map((r, i) => <tr key={i}><td className="text-muted whitespace-nowrap">{ago(r.ago_s)}</td><td className="font-mono text-[12.5px]">{r.component}</td><td className="break-words">{r.message}</td></tr>)}
          </Table>
        </Panel>)}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ switches */
interface Sw { name: string; label: string; help: string; on: boolean; default: boolean }

export function DevSwitches() {
  const { data, error, setData } = usePoll<Sw[]>("/api/dev/switches");
  const [err, setErr] = useState("");
  const flip = async (s: Sw) => {
    if (!window.confirm(`${s.on ? "Turn OFF" : "Turn ON"} “${s.label}”? This affects every user immediately and is written to the audit log.`)) return;
    try { setData(await api<Sw[]>(`/api/dev/switches/${s.name}`, { method: "PUT", json: { on: !s.on } })); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Page title="Switches" sub="Global controls for the whole app. Every change takes effect within a few seconds and is written to the audit log.">
      <ErrorBox text={error || err} />
      <div className="grid gap-3 max-w-[900px]">
        {data?.map((s) => (
          <div key={s.name} className={`card px-5 py-4 flex items-center gap-4 ${!s.on && s.default ? "border-sell/50" : ""}`}>
            <div className="flex-1">
              <div className="flex items-center gap-2"><span className="font-semibold text-[15.5px]">{s.label}</span><Badge tone={s.on ? "ok" : "fail"}>{s.on ? "On" : "Off"}</Badge></div>
              <div className="text-[13.5px] text-muted mt-1">{s.help}</div>
              <div className="text-[12px] text-faint mt-1 font-mono">{s.name}</div>
            </div>
            <button onClick={() => flip(s)} className={`rounded-full px-4 py-2 text-[13.5px] font-medium ${s.on ? "border border-sell/50 text-sell hover:bg-sellbg/50" : "bg-ink text-white"}`}>{s.on ? "Turn off" : "Turn on"}</button>
          </div>))}
      </div>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ sessions */
interface Sess { id: number; user: string; name: string; role: string; device: string; ip: string; signed_in: string; last_seen: string; idle_min: number; state: string; read_only: boolean }

export function DevSessions() {
  const { data, error, reload } = usePoll<Sess[]>("/api/dev/sessions", 15000);
  const [err, setErr] = useState("");
  return (
    <Page title="Sessions" sub="Every signed-in browser right now. A page that stops calling the server for 2 minutes counts as gone quiet. Signing someone out ends that browser's session at once.">
      <ErrorBox text={error || err} />
      <Panel pad={false}><div className="px-5 py-2">
        <Table head={["User", "Role", "Device", "Address", "Signed in", "Last seen", "Idle", "State", ""]}>
          {data?.map((s) => (
            <tr key={s.id}><td><div className="font-medium">{s.name}</div><div className="text-muted text-[12.5px]">{s.user}</div></td><td>{s.role}{s.read_only ? " · view-as" : ""}</td>
              <td className="whitespace-nowrap">{s.device}</td><td className="text-muted">{s.ip}</td><td className="whitespace-nowrap">{when(s.signed_in)}</td>
              <td className="whitespace-nowrap">{when(s.last_seen)}</td><td>{s.idle_min} min</td>
              <td><Badge tone={s.state === "online" ? "ok" : "muted"}>{s.state}</Badge></td>
              <td><Btn tone="danger" onClick={() => window.confirm(`Sign out ${s.user} on ${s.device}?`) && api(`/api/dev/sessions/${s.id}/signout`, { method: "POST" }).then(reload).catch((e) => setErr(e.message))}>Sign out</Btn></td></tr>))}
        </Table>
      </div></Panel>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ login attempts */
export function DevLogins() {
  const [failed, setFailed] = useState(false);
  const { data, error } = usePoll<{ failed_last_hour: number; policy: string; items: { ts: string; email: string; success: boolean; reason: string; ip: string; device: string }[] }>(`/api/dev/logins?only_failed=${failed}`, 15000);
  const tone: Record<string, string> = { ok: "ok", bad_credentials: "fail", locked: "warn", disabled: "muted" };
  return (
    <Page title="Login attempts" badge={data && <Badge tone={data.failed_last_hour ? "warn" : "ok"}>{data.failed_last_hour} failed in the last hour</Badge>}
          right={<label className="flex items-center gap-2 text-[13.5px]"><input type="checkbox" checked={failed} onChange={(e) => setFailed(e.target.checked)} />failed only</label>}
          sub={data?.policy}>
      <ErrorBox text={error} />
      <Panel pad={false}><div className="px-5 py-2">
        <Table head={["When (IST)", "Email", "What happened", "Details"]}>
          {data?.items.map((a, i) => (
            <tr key={i}><td className="whitespace-nowrap">{when(a.ts)}</td><td>{a.email}</td>
              <td><Badge tone={tone[a.reason] ?? "muted"}>{a.success ? "login.success" : `login.${a.reason}`}</Badge></td>
              <td className="text-muted">from {a.ip || "?"} · {a.device}</td></tr>))}
        </Table>
      </div></Panel>
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ roles */
export function DevRoles() {
  const { data, error } = usePoll<{ roles: string[]; matrix: Record<string, string | boolean>[]; rules: string[] }>("/api/dev/roles");
  return (
    <Page title="Roles & permissions">
      <ErrorBox text={error} />
      {data && <>
        <Panel><Table head={["Permission", ...data.roles]}>
          {data.matrix.map((r) => <tr key={String(r.permission)}><td className="font-mono text-[13px]">{String(r.permission)}</td>
            {data.roles.map((role) => <td key={role} className={r[role] ? "text-up" : "text-faint"}>{r[role] ? "✓" : "–"}</td>)}</tr>)}
        </Table></Panel>
        <Panel title="Rules"><ul className="list-disc pl-5 space-y-1.5 text-[14px]">{data.rules.map((r) => <li key={r}>{r}</li>)}</ul></Panel>
      </>}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ system info */
interface InfoData {
  uptime_s: number; python: string; fastapi: string; sqlalchemy: string; revision: string | null; environment: string; feed_mode: string; users: number;
  sessions_active: number; audit_rows: number; incidents: number; platform: string; database: string;
  files: { file: string; mb: number }[]; backups: { file: string; mb: number; at: string }[]; checks: { name: string; ok: boolean; detail: string }[];
}

export function DevInfo() {
  const { data, error } = usePoll<InfoData>("/api/dev/info", 30000);
  return (
    <Page title="System info">
      <ErrorBox text={error} />
      {data && <>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
          <Stat label="Uptime" value={`${(data.uptime_s / 3600).toFixed(1)} h`} /><Stat label="Python" value={data.python} /><Stat label="FastAPI" value={data.fastapi} />
          <Stat label="Users" value={data.users} /><Stat label="Sessions active" value={data.sessions_active} /><Stat label="Audit rows" value={data.audit_rows} />
          <Stat label="Incidents" value={data.incidents} />
        </div>
        <Panel title="Configuration checks">
          {data.checks.map((c) => <div key={c.name} className="flex flex-wrap items-center gap-3 py-2 border-t border-line first:border-0 text-[14px]">
            <Badge tone={c.ok ? "ok" : "warn"}>{c.ok ? "OK" : "Check"}</Badge><span className="font-medium w-[200px]">{c.name}</span><span className="text-muted">{c.detail}</span></div>)}
        </Panel>
        <Panel title="Database" right={<span className="text-[12.5px] text-muted break-all">{data.database}</span>}>
          <Table head={["File", "Size (MB)"]}>{data.files.map((f) => <tr key={f.file}><td className="font-mono text-[13px]">{f.file}</td><td>{f.mb}</td></tr>)}</Table>
        </Panel>
        <Panel title="Backups">
          {data.backups.length === 0 ? <div className="text-muted py-3">No backup-*.db files found next to the database.</div> :
            <Table head={["File", "Size (MB)", "Taken"]}>{data.backups.map((b) => <tr key={b.file}><td className="font-mono text-[13px]">{b.file}</td><td>{b.mb}</td><td>{when(b.at)}</td></tr>)}</Table>}
        </Panel>
        <div className="text-[12.5px] text-muted">{data.platform} · environment {data.environment} · feed {data.feed_mode}{data.revision ? ` · release ${data.revision.slice(0, 7)}` : ""}</div>
      </>}
    </Page>
  );
}

/* ------------------------------------------------------------------------------------------------ live logs */
export function DevLogs() {
  const [level, setLevel] = useState("");
  const [follow, setFollow] = useState(true);
  const { data, error } = usePoll<{ lines: string[]; bytes: number }>(`/api/dev/logs?lines=500&level=${level}`, follow ? 3000 : 0);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [data, follow]);
  return (
    <Page title="Live logs" right={<div className="flex items-center gap-3 text-[13px]">
      <select className="rounded-full border border-line px-3 py-1.5 bg-white" value={level} onChange={(e) => setLevel(e.target.value)}>
        <option value="">all lines</option><option value="WARNING">warnings and errors</option><option value="ERROR">errors only</option></select>
      <label className="flex items-center gap-1.5"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />follow (3 s)</label>
      {data && <span className="text-muted">{(data.bytes / 1024).toFixed(0)} KB</span>}</div>}
          sub="The last lines the backend wrote since it started. Passwords, tokens, cookies and secrets are masked before they leave the server.">
      <ErrorBox text={error} />
      <pre ref={box} className="rounded-2xl bg-[#0d1424] text-[#d6deeb] text-[12.5px] leading-[1.55] p-4 h-[calc(100vh-260px)] min-h-[320px] overflow-auto whitespace-pre-wrap break-all">
        {data?.lines.map((l, i) => <div key={i} className={/ ERROR | CRITICAL /.test(l) ? "text-[#ff8a8a]" : / WARNING /.test(l) ? "text-[#ffd479]" : ""}>{l}</div>)}
      </pre>
    </Page>
  );
}
