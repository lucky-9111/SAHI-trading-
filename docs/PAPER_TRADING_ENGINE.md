# Paper trading: order management and execution

SAHI never sends orders to a broker. Every fill is simulated in the backend (`backend/app/trading/engine.py`) against live Angel One
market data. The frontend can place, read and cancel orders; it cannot fill, price or change the status of one.

## Market status

`app/trading/market_status.py` is the single authority. It uses the server clock in IST and the editable market calendar
(`market_calendar` table, managed with `scripts/calendar_admin.py`).

| State | When (NSE / BSE cash) | Orders execute? |
|---|---|---|
| `PRE_OPEN` | 09:00–09:15 | No: queued until the open (the call auction is not simulated) |
| `OPEN` | 09:15–15:30, plus special sessions such as Muhurat | Yes |
| `POST_CLOSE` | 15:40–16:00 | No (the closing session is not simulated) |
| `CLOSED` | any other time on a trading day | No |
| `WEEKEND` / `HOLIDAY` | Saturday, Sunday, exchange holidays | No |

NFO and BFO have no pre-open or post-close state. MCX trades 09:00–23:30, or until 23:55 while the US is on daylight saving time.
Holidays come only from the calendar table. Load each year's list with `calendar_admin.py sync-nse`, or add days by hand. A holiday
that is missing from the table is treated as a trading day.

API: `GET /api/market/sessions`.

## Order types and lifecycle

Order types: `MARKET`, `LIMIT`, `SL` (stop-loss limit: trigger plus limit price) and `SL-M` (stop-loss market). The old `TRIGGER`
type is still accepted and is stored as `SL-M`.

```
place --closed, REJECT mode (default)--> REJECTED, nothing bought; the order panel shows a "Market is closed" dialog
      --closed, QUEUE mode (AMO, opt-in)--> PENDING --first fresh price of the next session--> executes / OPEN / TRIGGER_PENDING
      (GTT orders are accepted in both modes)
      --open-->  MARKET: FILLED (PENDING if no fresh price yet)   LIMIT: OPEN   SL / SL-M: TRIGGER_PENDING
TRIGGER_PENDING --trigger hit--> SL-M executes at market; SL becomes OPEN at its limit price
OPEN / PARTIALLY_FILLED --limit hit--> PARTIALLY_FILLED / FILLED
working orders --cancel--> CANCELLED      --DAY validity ends at the session close--> EXPIRED
a fill that cannot be booked (funds, opposite position, position gone) --> REJECTED (quantity already filled stays filled)
```

A SELL against an open long position (or a BUY against a short) is an exit order (`reduce_only`). It closes that position and books a
trade. Its quantity can never exceed the position. Stop-loss and target levels belong to new positions, not to exit orders. The
Portfolio "Exit" button places a MARKET exit order, so exits follow the same market-hours rules as entries.

## Execution assumptions

1. **Fresh prices only.** A price may be used for a fill only if it traded in the current session:
   - a websocket tick whose exchange timestamp falls inside today's session, or
   - the quote API's `exchTradeTime` falling inside today's session.

   Right after the open, the broker still reports the previous close as LTP; that is refused. A queued after-market order also needs a
   price stamped at or after its own first session. When the feed is down and the stored price is stale, nothing fills.
2. **Bid/ask.** When a fresh quote includes 5-level depth (`PAPER_DEPTH_FILLS=true`, the default), a BUY takes the asks and a SELL takes
   the bids, walking the levels. The fill price is the volume-weighted average of the levels used.
3. **Partial fills.** If the visible size is smaller than the order, only the visible size fills. The rest keeps working on later
   prices. This is a simplification: 5 levels are not the whole book, and real NSE market orders do not rest.
4. **No depth.** When no depth is available, the whole remaining quantity fills at the last traded price.
5. **Slippage.** Adverse slippage (per-portfolio setting, otherwise `PAPER_SLIPPAGE_PCT`) applies to market and stop-market fills, and to
   automatic stop-loss exits. It does not apply to limit fills, which never fill worse than their limit.
6. **When a limit or trigger is hit.** A limit or trigger counts as hit when the LTP reaches it. Queue position at that price is not
   modelled, so a limit "touched" once counts as filled if the book allows. Gaps fill at the first price seen, which can be worse than a
   stop.
7. **Funds.** Funds are checked when the order is placed, using a reference price (limit, trigger or last price), and checked again on
   every fill. Funds are not blocked while an order is pending.
8. **Margins and charges** are estimates (see `charges.py`).

## Reliability

- **Atomic state changes.** Every state change, its ledger entry, the position update, the trade log and the notification are written in
  one database transaction, under a process-wide lock.
- **No double fills.** A fill is a compare-and-swap on `(order id, filled_quantity, working status)`. Each fill posts exactly one ledger
  entry, keyed `order-<id>-fill-<n>`. The same price seen twice, by two workers or after a restart, cannot fill twice.
- **Restart safe.** Orders are only in the database. After a restart, the execution worker (`poller.py`, every 5 s) and the tick
  pipeline (`live/paper.py`) pick up working orders, and expire DAY orders whose session ended.
- **Notifications.** A notification is pushed to the browser (websocket event `notification`) only after its transaction commits. Tabs
  catch up with `GET /api/notifications?after_id=`. Order notifications also form each order's history in
  `GET /api/accounts/{id}/orders/{order_id}`.

## Database changes

Columns are added at startup by `ensure_columns()`, and `app/database/migrations.py` converts existing rows. The migration is idempotent
and does not touch fills, positions, trades or the ledger.

- **orders:** `trigger_price`, `filled_quantity`, `after_market`, `reduce_only`, `triggered_at`, `updated_at`. `status` is widened to
  20 characters.
- **trades:** `order_id`.
- **notifications:** `account_id`, `order_id`, `kind`, `level`.
- **risk_settings:** `after_hours_mode` (`QUEUE` or `REJECT`), `slippage_pct`.

Existing rows are converted as follows:

| Old row | New row |
|---|---|
| `EXECUTED` | `FILLED` |
| `TRIGGER` order type | `SL-M`, with the trigger moved to `trigger_price` |
| pending `LIMIT` | `OPEN` |
| pending stop order | `TRIGGER_PENDING` |
| "Day order expired" | `EXPIRED` |
