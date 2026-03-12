import os
import json
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import engine, get_db, Base
from models import User, Asset, PortfolioTransaction, PriceCache
from schemas import (
    UserRegister, UserLogin, TokenResponse,
    AssetOut, TransactionOut, PortfolioOut, HoldingOut,
    BuyRequest, SellRequest, TradeResponse, LeaderboardEntry
)
from auth import hash_password, verify_password, create_access_token, get_current_user
from market_data import get_asset_price, fetch_stock_timeseries, fetch_all_crypto_prices

load_dotenv()

# Create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="InvestSim API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        full_name=data.full_name,
        email=data.email,
        password_hash=hash_password(data.password),
        country=data.country,
        experience_level=data.experience_level,
        wallet_balance=Decimal("10000.00")
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "wallet_balance": float(user.wallet_balance),
            "country": user.country,
            "experience_level": user.experience_level,
            "member_since": user.created_at.year if user.created_at else 2024
        }
    }


@app.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "wallet_balance": float(user.wallet_balance),
            "country": user.country,
            "experience_level": user.experience_level,
            "member_since": user.created_at.year if user.created_at else 2024
        }
    }


@app.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "wallet_balance": float(current_user.wallet_balance),
        "country": current_user.country,
        "experience_level": current_user.experience_level,
        "member_since": current_user.created_at.year if current_user.created_at else 2024,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None
    }


# ─────────────────────────────────────────────────────────────
# ASSETS ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/assets", response_model=List[AssetOut])
async def get_assets(db: Session = Depends(get_db)):
    """Returns all 10 assets with live prices from APIs"""
    assets = db.query(Asset).filter(Asset.is_active == True).all()

    # Fetch crypto prices in one batch call
    crypto_prices = await fetch_all_crypto_prices()

    result = []
    for asset in assets:
        price_data = None
        if asset.api_source == "coingecko" and crypto_prices:
            price_data = crypto_prices.get(asset.coingecko_id)
        elif asset.api_source == "twelvedata":
            from market_data import fetch_stock_price
            price_data = await fetch_stock_price(asset.symbol)

        sparkline = []
        if price_data and price_data.get("sparkline"):
            sparkline = price_data["sparkline"]

        result.append(AssetOut(
            id=asset.id,
            symbol=asset.symbol,
            name=asset.name,
            type=asset.type,
            api_source=asset.api_source,
            price=price_data.get("price") if price_data else None,
            change_24h=price_data.get("change_24h") if price_data else None,
            change_7d=price_data.get("change_7d") if price_data else None,
            change_1h=price_data.get("change_1h") if price_data else None,
            volume=price_data.get("volume") if price_data else None,
            market_cap=price_data.get("market_cap") if price_data else None,
            high_day=price_data.get("high_day") if price_data else None,
            low_day=price_data.get("low_day") if price_data else None,
            sparkline=sparkline
        ))

    return result


@app.get("/asset/{asset_id}")
async def get_asset_detail(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns asset detail + price history + user transactions"""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get live price
    price_data = await get_asset_price(asset)

    # Get chart data
    chart_data = []
    if asset.api_source == "twelvedata":
        chart_data = await fetch_stock_timeseries(asset.symbol, interval="1h", outputsize=168)
    elif asset.api_source == "coingecko":
        all_crypto = await fetch_all_crypto_prices()
        if all_crypto and asset.coingecko_id in all_crypto:
            sparkline = all_crypto[asset.coingecko_id].get("sparkline", [])
            # Convert sparkline to chart format
            now = datetime.utcnow()
            for i, price in enumerate(sparkline):
                dt = now.replace(hour=i % 24, minute=0, second=0)
                chart_data.append({"datetime": dt.isoformat(), "close": price})

    # Get user transactions for this asset
    transactions = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.user_id == current_user.id,
        PortfolioTransaction.asset_id == asset_id
    ).order_by(PortfolioTransaction.created_at.desc()).all()

    tx_list = [
        {
            "id": t.id,
            "qty": float(t.qty),
            "price": float(t.price),
            "total_amount": float(t.total_amount),
            "transaction_type": t.transaction_type,
            "created_at": t.created_at.isoformat()
        }
        for t in transactions
    ]

    # Calculate holdings
    buy_qty = sum(float(t.qty) for t in transactions if t.transaction_type == "buy")
    sell_qty = sum(float(t.qty) for t in transactions if t.transaction_type == "sell")
    held_qty = buy_qty - sell_qty

    total_invested = sum(float(t.qty) * float(t.price) for t in transactions if t.transaction_type == "buy")
    avg_cost = (total_invested / buy_qty) if buy_qty > 0 else 0

    current_price = price_data.get("price", 0) if price_data else 0
    market_value = held_qty * current_price
    profit_loss = market_value - (held_qty * avg_cost) if held_qty > 0 else 0

    return {
        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "type": asset.type,
            "api_source": asset.api_source,
        },
        "price_data": price_data,
        "chart_data": chart_data,
        "holdings": {
            "qty": held_qty,
            "avg_cost": avg_cost,
            "market_value": market_value,
            "profit_loss": profit_loss,
            "profit_loss_pct": ((profit_loss / (held_qty * avg_cost)) * 100) if (held_qty > 0 and avg_cost > 0) else 0
        },
        "transactions": tx_list
    }


# ─────────────────────────────────────────────────────────────
# TRADE ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.post("/buy", response_model=TradeResponse)
async def buy_asset(
    req: BuyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    asset = db.query(Asset).filter(Asset.id == req.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    price_data = await get_asset_price(asset)
    if not price_data or not price_data.get("price"):
        raise HTTPException(status_code=503, detail="Could not fetch live price")

    current_price = float(price_data["price"])
    total_cost = current_price * req.qty

    if float(current_user.wallet_balance) < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds. Need ${total_cost:.2f}, have ${float(current_user.wallet_balance):.2f}"
        )

    # Deduct from wallet
    current_user.wallet_balance = Decimal(str(float(current_user.wallet_balance) - total_cost))

    # Record transaction
    tx = PortfolioTransaction(
        user_id=current_user.id,
        asset_id=asset.id,
        qty=Decimal(str(req.qty)),
        price=Decimal(str(current_price)),
        total_amount=Decimal(str(total_cost)),
        transaction_type="buy"
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return TradeResponse(
        success=True,
        message=f"Successfully bought {req.qty} {asset.symbol} at ${current_price:.2f}",
        transaction_id=tx.id,
        new_wallet_balance=float(current_user.wallet_balance)
    )


@app.post("/sell", response_model=TradeResponse)
async def sell_asset(
    req: SellRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    asset = db.query(Asset).filter(Asset.id == req.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check user holdings
    buys = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.user_id == current_user.id,
        PortfolioTransaction.asset_id == req.asset_id,
        PortfolioTransaction.transaction_type == "buy"
    ).all()
    sells = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.user_id == current_user.id,
        PortfolioTransaction.asset_id == req.asset_id,
        PortfolioTransaction.transaction_type == "sell"
    ).all()

    held = sum(float(t.qty) for t in buys) - sum(float(t.qty) for t in sells)
    if held < req.qty:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient holdings. You have {held:.4f} {asset.symbol}"
        )

    price_data = await get_asset_price(asset)
    if not price_data or not price_data.get("price"):
        raise HTTPException(status_code=503, detail="Could not fetch live price")

    current_price = float(price_data["price"])
    total_proceeds = current_price * req.qty

    # Add to wallet
    current_user.wallet_balance = Decimal(str(float(current_user.wallet_balance) + total_proceeds))

    tx = PortfolioTransaction(
        user_id=current_user.id,
        asset_id=asset.id,
        qty=Decimal(str(req.qty)),
        price=Decimal(str(current_price)),
        total_amount=Decimal(str(total_proceeds)),
        transaction_type="sell"
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return TradeResponse(
        success=True,
        message=f"Successfully sold {req.qty} {asset.symbol} at ${current_price:.2f}",
        transaction_id=tx.id,
        new_wallet_balance=float(current_user.wallet_balance)
    )


# ─────────────────────────────────────────────────────────────
# PORTFOLIO ENDPOINT
# ─────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def get_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    transactions = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.user_id == current_user.id
    ).all()

    # Build holdings map
    holdings_map = {}
    for tx in transactions:
        aid = tx.asset_id
        if aid not in holdings_map:
            holdings_map[aid] = {"buy_qty": 0, "sell_qty": 0, "buy_total": 0}
        if tx.transaction_type == "buy":
            holdings_map[aid]["buy_qty"] += float(tx.qty)
            holdings_map[aid]["buy_total"] += float(tx.qty) * float(tx.price)
        else:
            holdings_map[aid]["sell_qty"] += float(tx.qty)

    # Get all crypto in one call
    crypto_prices = await fetch_all_crypto_prices()

    holdings_list = []
    total_market_value = 0
    total_invested = 0

    for asset_id, h in holdings_map.items():
        held_qty = h["buy_qty"] - h["sell_qty"]
        if held_qty <= 0.000001:
            continue

        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            continue

        # Get current price
        price_data = None
        if asset.api_source == "coingecko" and crypto_prices:
            price_data = crypto_prices.get(asset.coingecko_id)
        elif asset.api_source == "twelvedata":
            from market_data import fetch_stock_price
            price_data = await fetch_stock_price(asset.symbol)

        current_price = price_data.get("price", 0) if price_data else 0
        avg_cost = h["buy_total"] / h["buy_qty"] if h["buy_qty"] > 0 else 0
        market_value = held_qty * current_price
        cost_basis = held_qty * avg_cost
        profit_loss = market_value - cost_basis

        total_market_value += market_value
        total_invested += cost_basis

        holdings_list.append({
            "asset_id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "type": asset.type,
            "qty": held_qty,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "profit_loss": profit_loss,
            "profit_loss_pct": ((profit_loss / cost_basis) * 100) if cost_basis > 0 else 0,
            "change_24h": price_data.get("change_24h") if price_data else 0
        })

    wallet = float(current_user.wallet_balance)
    total_value = wallet + total_market_value
    total_pl = total_market_value - total_invested

    return {
        "wallet_balance": wallet,
        "total_portfolio_value": total_value,
        "total_invested": total_invested,
        "total_profit_loss": total_pl,
        "total_profit_loss_pct": ((total_pl / total_invested) * 100) if total_invested > 0 else 0,
        "holdings": holdings_list
    }


# ─────────────────────────────────────────────────────────────
# TRANSACTIONS HISTORY
# ─────────────────────────────────────────────────────────────

@app.get("/transactions")
async def get_transactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    txs = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.user_id == current_user.id
    ).order_by(PortfolioTransaction.created_at.desc()).limit(50).all()

    result = []
    for t in txs:
        asset = db.query(Asset).filter(Asset.id == t.asset_id).first()
        result.append({
            "id": t.id,
            "asset_id": t.asset_id,
            "asset_symbol": asset.symbol if asset else "?",
            "asset_name": asset.name if asset else "?",
            "qty": float(t.qty),
            "price": float(t.price),
            "total_amount": float(t.total_amount),
            "transaction_type": t.transaction_type,
            "created_at": t.created_at.isoformat()
        })
    return result


# ─────────────────────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────────────────────

@app.get("/leaderboard")
async def get_leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).all()

    # Fetch crypto prices once
    crypto_prices = await fetch_all_crypto_prices()

    entries = []
    for user in users:
        transactions = db.query(PortfolioTransaction).filter(
            PortfolioTransaction.user_id == user.id
        ).all()

        total_market_value = 0
        total_invested = 0
        holdings_map = {}

        for tx in transactions:
            aid = tx.asset_id
            if aid not in holdings_map:
                holdings_map[aid] = {"buy_qty": 0, "sell_qty": 0, "buy_total": 0}
            if tx.transaction_type == "buy":
                holdings_map[aid]["buy_qty"] += float(tx.qty)
                holdings_map[aid]["buy_total"] += float(tx.qty) * float(tx.price)
            else:
                holdings_map[aid]["sell_qty"] += float(tx.qty)

        for asset_id, h in holdings_map.items():
            held_qty = h["buy_qty"] - h["sell_qty"]
            if held_qty <= 0:
                continue
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset:
                continue
            price_data = None
            if asset.api_source == "coingecko" and crypto_prices:
                price_data = crypto_prices.get(asset.coingecko_id)
            elif asset.api_source == "twelvedata":
                from market_data import fetch_stock_price
                price_data = await fetch_stock_price(asset.symbol)

            current_price = price_data.get("price", 0) if price_data else 0
            total_market_value += held_qty * current_price
            total_invested += h["buy_total"] - (h["sell_qty"] * (h["buy_total"] / h["buy_qty"] if h["buy_qty"] > 0 else 0))

        wallet = float(user.wallet_balance)
        total_value = wallet + total_market_value
        pl = total_market_value - total_invested if total_invested > 0 else 0

        entries.append({
            "user_id": user.id,
            "full_name": user.full_name,
            "total_value": total_value,
            "profit_loss": pl,
            "profit_loss_pct": ((pl / 10000) * 100)
        })

    entries.sort(key=lambda x: x["total_value"], reverse=True)
    for i, e in enumerate(entries):
        e["rank"] = i + 1

    return entries[:20]


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}