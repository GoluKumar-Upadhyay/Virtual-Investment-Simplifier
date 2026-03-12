from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

# ─── Auth Schemas ─────────────────────────────────────────────
class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    country: Optional[str] = "United States"
    experience_level: Optional[str] = "Beginner"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

# ─── Asset Schemas ────────────────────────────────────────────
class AssetOut(BaseModel):
    id: int
    symbol: str
    name: str
    type: str
    api_source: str
    price: Optional[float] = None
    change_24h: Optional[float] = None
    change_7d: Optional[float] = None
    change_1h: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    high_day: Optional[float] = None
    low_day: Optional[float] = None
    sparkline: Optional[List[float]] = None

    class Config:
        from_attributes = True

# ─── Transaction Schemas ──────────────────────────────────────
class TransactionOut(BaseModel):
    id: int
    asset_id: int
    asset_symbol: str
    asset_name: str
    qty: float
    price: float
    total_amount: float
    transaction_type: str
    created_at: datetime

    class Config:
        from_attributes = True

# ─── Portfolio Schemas ────────────────────────────────────────
class HoldingOut(BaseModel):
    asset_id: int
    symbol: str
    name: str
    type: str
    qty: float
    avg_cost: float
    current_price: float
    market_value: float
    profit_loss: float
    profit_loss_pct: float

class PortfolioOut(BaseModel):
    wallet_balance: float
    total_portfolio_value: float
    total_invested: float
    total_profit_loss: float
    total_profit_loss_pct: float
    holdings: List[HoldingOut]

# ─── Trade Schemas ────────────────────────────────────────────
class BuyRequest(BaseModel):
    asset_id: int
    qty: float

class SellRequest(BaseModel):
    asset_id: int
    qty: float

class TradeResponse(BaseModel):
    success: bool
    message: str
    transaction_id: Optional[int] = None
    new_wallet_balance: Optional[float] = None

# ─── Leaderboard Schemas ──────────────────────────────────────
class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    full_name: str
    total_value: float
    profit_loss: float
    profit_loss_pct: float