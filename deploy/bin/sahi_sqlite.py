"""SQLite helpers for the SAHI server scripts (standard library only; run with `python3 -I`).

  backup  <src.db> <dst.db>   online, consistent copy via the SQLite backup API (safe while the app is writing
                              in WAL mode), then integrity_check + row counts of the copy must match the source
  verify  <file.db>           PRAGMA integrity_check == ok and the core tables exist
  counts  <file.db>           row count per table (for restore reports)

Exit code 0 = ok. Prints only table names and counts - never row contents.
"""
import json
import sqlite3
import sys

CORE_TABLES = {"users", "trading_accounts", "virtual_funds_ledger", "orders", "positions", "trades"}


def connect(path: str, mode: str) -> sqlite3.Connection:
    """mode: ro | rw (must exist - never creates an empty database by accident) | rwc (backup target only)."""
    uri = f"file:{path}?mode={mode}"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [r[0] for r in rows]


def counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables(con)}


def integrity(con: sqlite3.Connection) -> str:
    return ",".join(r[0] for r in con.execute("PRAGMA integrity_check").fetchall())


def cmd_backup(src: str, dst: str) -> int:
    s = connect(src, "rw")   # not read-only: a WAL database needs its -shm to be writable
    d = connect(dst, "rwc")
    with d:
        s.backup(d, pages=1024, sleep=0.05)
    src_tables = set(tables(s))
    s.close()
    # The app keeps writing while we copy, so the copy is compared with nothing but itself: it must pass a full
    # integrity check and contain every core table the source had.
    d.execute("PRAGMA journal_mode=DELETE")  # the backup is one self-contained file (no -wal / -shm)
    ok = integrity(d)
    dc = counts(d)
    d.close()
    missing = sorted((CORE_TABLES & src_tables) - set(dc))
    if ok != "ok" or missing:
        print(json.dumps({"ok": False, "integrity": ok[:200], "missing_core_tables": missing}))
        return 1
    print(json.dumps({"ok": True, "tables": len(dc), "rows": sum(dc.values())}))
    return 0


def cmd_verify(path: str) -> int:
    con = connect(path, "ro")
    ok = integrity(con)
    have = set(tables(con))
    con.close()
    missing = sorted(CORE_TABLES - have)
    res = {"ok": ok == "ok" and not missing, "integrity": ok[:200], "missing_core_tables": missing}
    print(json.dumps(res))
    return 0 if res["ok"] else 1


def cmd_counts(path: str) -> int:
    con = connect(path, "ro")
    print(json.dumps(counts(con), indent=1))
    con.close()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "backup":
        return cmd_backup(argv[1], argv[2])
    if len(argv) == 2 and argv[0] == "verify":
        return cmd_verify(argv[1])
    if len(argv) == 2 and argv[0] == "counts":
        return cmd_counts(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
