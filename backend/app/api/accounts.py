from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_account
from app.database.session import get_db
from app.models import LedgerEntry, TradingAccount, User
from app.schemas import AccountCreate, AccountOut, FundsIn, LedgerOut
from app.services import accounts as svc

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _out(db: Session, a: TradingAccount) -> AccountOut:
    return AccountOut(id=a.id, name=a.name, initial_capital=a.initial_capital, balance=svc.get_balance(db, a.id))


@router.get("", response_model=list[AccountOut])
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(TradingAccount).where(TradingAccount.user_id == user.id, TradingAccount.is_active)).all()
    return [_out(db, a) for a in rows]


@router.post("", response_model=AccountOut, status_code=201)
def create(body: AccountCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return _out(db, svc.create_account(db, user.id, body.name, body.initial_capital))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this name already exists")


@router.post("/{account_id}/deposit", response_model=LedgerOut)
def deposit(body: FundsIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    try:
        return svc.deposit(db, acc, body.amount, body.note)
    except svc.LedgerError as e:
        raise HTTPException(400, str(e))


@router.post("/{account_id}/withdraw", response_model=LedgerOut)
def withdraw(body: FundsIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    try:
        return svc.withdraw(db, acc, body.amount, body.note)
    except svc.LedgerError as e:
        raise HTTPException(400, str(e))


@router.get("/{account_id}/ledger", response_model=list[LedgerOut])
def ledger(acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    return db.scalars(select(LedgerEntry).where(LedgerEntry.account_id == acc.id).order_by(LedgerEntry.id.desc())).all()
