from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    initial_capital: Decimal = Field(default=Decimal("1000000"), gt=0, le=Decimal("1000000000"))


class AccountOut(BaseModel):
    id: int
    name: str
    initial_capital: Decimal
    balance: Decimal


class FundsIn(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("1000000000"))
    note: str = Field(default="", max_length=255)


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entry_type: str
    amount: Decimal
    balance_after: Decimal
    description: str
    created_at: datetime
