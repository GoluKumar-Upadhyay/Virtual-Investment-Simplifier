from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    country = Column(String(100), default="United States")
    experience_level = Column(String(50), default="Beginner")
    wallet_balance = Column(Numeric(15, 2), default=10000.00)
    created_at = Column(DateTime, default=func.now())
    last_login = Column(DateTime, default=func.now())

    transactions = relationship("PortfolioTransaction", back_populates="user")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(String(10), nullable=False)       # 'stock' or 'crypto'
    api_source = Column(String(20), nullable=False)  # 'twelvedata' or 'coingecko'
    coingecko_id = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)

    transactions = relationship("PortfolioTransaction", back_populates="asset")
    price_caches = relationship("PriceCache", back_populates="asset")


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    qty = Column(Numeric(18, 8), nullable=False)
    price = Column(Numeric(15, 4), nullable=False)
    total_amount = Column(Numeric(15, 4), nullable=False)
    transaction_type = Column(String(4), nullable=False)  # 'buy' or 'sell'
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="transactions")
    asset = relationship("Asset", back_populates="transactions")


class PriceCache(Base):
    __tablename__ = "price_cache"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    price = Column(Numeric(15, 4), nullable=False)
    change_24h = Column(Numeric(8, 4))
    change_7d = Column(Numeric(8, 4))
    change_1h = Column(Numeric(8, 4))
    volume = Column(Numeric(20, 2))
    market_cap = Column(Numeric(20, 2))
    high_day = Column(Numeric(15, 4))
    low_day = Column(Numeric(15, 4))
    sparkline_data = Column(Text)
    cached_at = Column(DateTime, default=func.now())

    asset = relationship("Asset", back_populates="price_caches")