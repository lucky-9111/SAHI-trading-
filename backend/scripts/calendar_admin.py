r"""Edit the market calendar (holidays, special sessions, late opens) without touching code. Changes are read within a minute.

    cd backend
    .venv\Scripts\python scripts\calendar_admin.py list
    .venv\Scripts\python scripts\calendar_admin.py holiday 2026-12-25 NSE "Christmas"
    .venv\Scripts\python scripts\calendar_admin.py special 2026-11-08 NSE 18:15 19:15 "Muhurat trading"
    .venv\Scripts\python scripts\calendar_admin.py late_open 2026-11-24 MCX 17:00 "Guru Nanak Jayanti"
    .venv\Scripts\python scripts\calendar_admin.py delete 2026-12-25 NSE
    .venv\Scripts\python scripts\calendar_admin.py sync-nse                # NSE's own F&O holiday list (best effort)
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.live import calendar  # noqa: E402
from app.models.live import MarketCalendarRow  # noqa: E402

NSE_URL = "https://www.nseindia.com/api/holiday-master?type=trading"


def main(argv: list[str]) -> None:
    Base.metadata.create_all(engine)
    if not argv or argv[0] == "list":
        with SessionLocal() as db:
            for r in db.scalars(select(MarketCalendarRow).order_by(MarketCalendarRow.date)):
                print(r.date, r.exchange, r.kind, r.start_time or "", r.end_time or "", r.note)
        return
    cmd = argv[0]
    with SessionLocal() as db:
        if cmd == "holiday":
            calendar.put(db, argv[1], argv[2], "holiday", note=" ".join(argv[3:]))
        elif cmd == "special":
            calendar.put(db, argv[1], argv[2], "special", argv[3], argv[4], " ".join(argv[5:]))
        elif cmd == "late_open":
            calendar.put(db, argv[1], argv[2], "late_open", argv[3], None, " ".join(argv[4:]))
        elif cmd == "delete":
            row = db.scalar(select(MarketCalendarRow).where(MarketCalendarRow.date == argv[1], MarketCalendarRow.exchange == calendar.canon(argv[2])))
            if row:
                db.delete(row)
                db.commit()
        elif cmd == "sync-nse":
            import datetime as dt

            req = urllib.request.Request(NSE_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                                           "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            n = 0
            for x in data.get("FO") or []:
                try:
                    d = dt.datetime.strptime(x["tradingDate"], "%d-%b-%Y").date().isoformat()
                except (KeyError, ValueError):
                    continue
                calendar.put(db, d, "NSE", "holiday", note=(x.get("description") or "Exchange holiday").strip()[:200])
                n += 1
            print(f"{n} NSE holidays stored")
        else:
            print(__doc__)
            return
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1:])
