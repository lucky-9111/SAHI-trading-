import { Route, Routes } from "react-router-dom";
import { AdminAnnouncements, AdminAudit, AdminCalendar, AdminOverview, AdminUsers } from "./AdminPages";
import ConsoleLayout from "./ConsoleLayout";
import { DevAngel, DevErrors, DevHealth, DevInfo, DevLogins, DevLogs, DevRoles, DevSessions, DevSwitches } from "./DevPages";

/** Admin and developer consoles: loaded on demand, so traders never download this code. */
export default function ConsoleApp({ kind }: { kind: "admin" | "dev" }) {
  return kind === "admin" ? (
    <Routes>
      <Route element={<ConsoleLayout kind="admin" />}>
        <Route index element={<AdminOverview />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="audit" element={<AdminAudit />} />
        <Route path="announcements" element={<AdminAnnouncements />} />
        <Route path="calendar" element={<AdminCalendar />} />
      </Route>
    </Routes>
  ) : (
    <Routes>
      <Route element={<ConsoleLayout kind="dev" />}>
        <Route index element={<DevHealth />} />
        <Route path="angel" element={<DevAngel />} />
        <Route path="errors" element={<DevErrors />} />
        <Route path="switches" element={<DevSwitches />} />
        <Route path="sessions" element={<DevSessions />} />
        <Route path="logins" element={<DevLogins />} />
        <Route path="roles" element={<DevRoles />} />
        <Route path="info" element={<DevInfo />} />
        <Route path="logs" element={<DevLogs />} />
      </Route>
    </Routes>
  );
}
