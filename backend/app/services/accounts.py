"""Account + virtual ledger logic. All balances are derived from the append-only ledger (Decimal math)."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, RiskSettings, Strategy, TradingAccount

TWO = Decimal("0.01")


class LedgerError(ValueError):
    pass


def to_money(value) -> Decimal:
    try:
        d = Decimal(str(value)).quantize(TWO)
    except (InvalidOperation, ValueError):
        raise LedgerError("Invalid amount")
    return d


def get_balance(db: Session, account_id: int) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.account_id == account_id))
    return Decimal(str(total)).quantize(TWO)


def _post(db: Session, account: TradingAccount, entry_type: str, amount: Decimal, description: str,
          idempotency_key: str | None = None) -> LedgerEntry:
    """Append a ledger row inside the caller's transaction. Rejects any posting that would overdraw."""
    if idempotency_key:
        existing = db.scalar(select(LedgerEntry).where(
            LedgerEntry.account_id == account.id, LedgerEntry.idempotency_key == idempotency_key))
        if existing:
            return existing  # duplicate request: do not post twice
    new_balance = get_balance(db, account.id) + amount
    if new_balance < 0:
        raise LedgerError("Insufficient virtual funds")
    entry = LedgerEntry(account_id=account.id, entry_type=entry_type, amount=amount, balance_after=new_balance,
                        description=description, idempotency_key=idempotency_key)
    db.add(entry)
    db.flush()
    return entry


post_entry = _post  # public alias for the trading engine


def create_account(db: Session, user_id: int, name: str, initial_capital: Decimal) -> TradingAccount:
    if initial_capital <= 0:
        raise LedgerError("Initial capital must be positive")
    acc = TradingAccount(user_id=user_id, name=name.strip(), initial_capital=initial_capital)
    acc.risk = RiskSettings()
    db.add(acc)
    db.flush()
    _post(db, acc, "INITIAL", initial_capital, "Initial virtual capital")
    db.commit()
    return acc


def deposit(db: Session, account: TradingAccount, amount: Decimal, note: str = "", key: str | None = None):
    if amount <= 0:
        raise LedgerError("Deposit must be positive")
    e = _post(db, account, "DEPOSIT", amount, note or "Virtual funds added", key)
    db.commit()
    return e


def withdraw(db: Session, account: TradingAccount, amount: Decimal, note: str = "", key: str | None = None):
    if amount <= 0:
        raise LedgerError("Withdrawal must be positive")
    e = _post(db, account, "WITHDRAWAL", -amount, note or "Virtual funds withdrawn", key)
    db.commit()
    return e


DEFAULT_STRATEGIES = ["Manual", "System 1", "GFS", "Advance GFS", "50 GFS", "PRD", "NRD", "CUP Pattern", "Top Bottom"]


def ensure_default_strategies(db: Session, user_id: int) -> None:
    """Idempotent: adds any missing default strategy, never touches existing ones (or user-created ones)."""
    have = set(db.scalars(select(Strategy.name).where(Strategy.user_id == user_id)).all())
    missing = [n for n in DEFAULT_STRATEGIES if n not in have]
    for name in missing:
        db.add(Strategy(user_id=user_id, name=name,
                        description="Discretionary trades" if name == "Manual" else ""))
    if missing:
        db.commit()
