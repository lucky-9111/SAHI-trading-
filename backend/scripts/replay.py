r"""Replay a recorded tick file through the whole live pipeline, offline (no broker, no market).

    cd backend
    .venv\Scripts\python scripts\replay.py ticks.jsonl                 # as fast as possible, prints the candles it built
    .venv\Scripts\python scripts\replay.py ticks.jsonl --speed 1       # real time
    .venv\Scripts\python scripts\replay.py ticks.jsonl --db            # also write the candles / fills to the database in DATABASE_URL
    .venv\Scripts\python scripts\replay.py --make-sample sample.jsonl  # write a tiny synthetic file to try it with

Record a file from the live market with  RECORD_TICKS=ticks.jsonl  set on the server (the receiver appends every raw message).
To see a replay in the browser instead, start the app with  FEED_MODE=replay REPLAY_FILE=ticks.jsonl REPLAY_SPEED=1.
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def make_sample(path: str) -> None:
    day = dt.datetime.now(IST)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    t0 = day.replace(hour=9, minute=15, second=0, microsecond=0)
    cum = 0
    with open(path, "w", encoding="utf-8") as f:
        for m in range(30):
            for sec, px in ((2, 100 + m * 0.1), (20, 101 + m * 0.1), (40, 99.5 + m * 0.1), (58, 100.4 + m * 0.1)):
                cum += 25
                ts = t0 + dt.timedelta(minutes=m, seconds=sec)
                f.write(json.dumps({"subscription_mode": 2, "exchange_type": 1, "token": '"2885"', "last_traded_price": int(px * 100),
                                    "exchange_timestamp": int(ts.timestamp() * 1000), "volume_trade_for_the_day": cum}) + "\n")
    print(f"wrote {path} (30 minutes of RELIANCE, token 2885)")


async def main(a) -> None:
    from app.live import replay
    from app.live.candles import Candle
    from app.live.pipeline import Pipeline

    pl = Pipeline(mode="replay", persist=a.db, timers=False)
    got: list[Candle] = []
    q = pl.bus.subscribe("candle")
    await pl.start()
    if not a.db:
        pl.index.setdefault("NSE:2885", (None, "RELIANCE"))
    summary = await replay.play(pl, a.file, a.speed)
    while not q.empty():
        got.append(q.get_nowait())
    await pl.stop()
    print(summary)
    for tf in ("1m", "5m", "15m", "1d"):
        cs = [c for c in got if c.tf == tf]
        print(f"{tf}: {len(cs)} candles")
        for c in cs[: a.show]:
            print(f"   {c.symbol:12} {c.start.astimezone(IST):%Y-%m-%d %H:%M}  O {c.open:.2f}  H {c.high:.2f}  L {c.low:.2f}  C {c.close:.2f}  V {c.volume}")
    print("health:", json.dumps(pl.health()["dropped_ticks"]), "errors:", pl.errors)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--speed", type=float, default=0.0, help="0 = as fast as possible, 1 = real time")
    ap.add_argument("--db", action="store_true", help="write candles and let the paper engine act on the database in DATABASE_URL")
    ap.add_argument("--show", type=int, default=5, help="candles to print per timeframe")
    ap.add_argument("--make-sample", metavar="PATH")
    args = ap.parse_args()
    if args.make_sample:
        make_sample(args.make_sample)
    elif args.file:
        asyncio.run(main(args))
    else:
        ap.print_help()
