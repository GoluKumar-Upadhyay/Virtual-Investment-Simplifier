import os
import json
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
COINGECKO_API_URL = os.getenv("COINGECKO_API_URL")

TWELVEDATA_BASE = "https://api.twelvedata.com"

# In-memory cache (60s TTL for prices)
_price_cache: Dict[str, Dict] = {}
_cache_ttl = 60  # seconds


def _is_cache_valid(key: str) -> bool:
    if key not in _price_cache:
        return False
    cached_at = _price_cache[key].get("_cached_at")
    if not cached_at:
        return False
    return (datetime.utcnow() - cached_at).total_seconds() < _cache_ttl


async def fetch_stock_price(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch real-time stock price from TwelveData API"""
    cache_key = f"stock_{symbol}"
    if _is_cache_valid(cache_key):
        return _price_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get real-time quote
            quote_url = f"{TWELVEDATA_BASE}/quote?symbol={symbol}&apikey={TWELVEDATA_API_KEY}"
            resp = await client.get(quote_url)
            data = resp.json()

            if data.get("status") == "error" or "code" in data:
                return None

            result = {
                "symbol": symbol,
                "price": float(data.get("close", 0)),
                "change_24h": float(data.get("percent_change", 0)),
                "change_1h": 0.0,
                "change_7d": float(data.get("fifty_two_week", {}).get("low", 0)) if isinstance(data.get("fifty_two_week"), dict) else 0.0,
                "volume": float(data.get("volume", 0)),
                "market_cap": 0.0,
                "high_day": float(data.get("high", 0)),
                "low_day": float(data.get("low", 0)),
                "open": float(data.get("open", 0)),
                "prev_close": float(data.get("previous_close", 0)),
                "sparkline": [],
                "_cached_at": datetime.utcnow()
            }

            _price_cache[cache_key] = result
            return result

    except Exception as e:
        print(f"TwelveData error for {symbol}: {e}")
        return None


async def fetch_stock_timeseries(symbol: str, interval: str = "1h", outputsize: int = 168) -> list:
    """Fetch time series data from TwelveData for charts"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{TWELVEDATA_BASE}/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}"
            resp = await client.get(url)
            data = resp.json()

            if data.get("status") == "error" or "code" in data:
                return []

            values = data.get("values", [])
            # Return as list of {datetime, close} for charting
            return [
                {
                    "datetime": v["datetime"],
                    "open": float(v["open"]),
                    "high": float(v["high"]),
                    "low": float(v["low"]),
                    "close": float(v["close"]),
                    "volume": float(v.get("volume", 0))
                }
                for v in reversed(values)
            ]
    except Exception as e:
        print(f"TwelveData timeseries error for {symbol}: {e}")
        return []


async def fetch_all_crypto_prices() -> Optional[Dict[str, Dict]]:
    """Fetch all crypto prices from CoinGecko in one call"""
    cache_key = "all_crypto"
    if _is_cache_valid(cache_key):
        return _price_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(COINGECKO_API_URL)
            coins = resp.json()

            if not isinstance(coins, list):
                return None

            result = {}
            for coin in coins:
                coin_id = coin.get("id", "")
                sparkline_prices = []
                if coin.get("sparkline_in_7d") and coin["sparkline_in_7d"].get("price"):
                    sparkline_prices = coin["sparkline_in_7d"]["price"][-24:]  # last 24 data pts

                result[coin_id] = {
                    "symbol": coin.get("symbol", "").upper(),
                    "price": float(coin.get("current_price", 0)),
                    "change_24h": float(coin.get("price_change_percentage_24h_in_currency", 0) or 0),
                    "change_1h": float(coin.get("price_change_percentage_1h_in_currency", 0) or 0),
                    "change_7d": float(coin.get("price_change_percentage_7d_in_currency", 0) or 0),
                    "volume": float(coin.get("total_volume", 0)),
                    "market_cap": float(coin.get("market_cap", 0)),
                    "high_day": float(coin.get("high_24h", 0)),
                    "low_day": float(coin.get("low_24h", 0)),
                    "sparkline": sparkline_prices,
                    "_cached_at": datetime.utcnow()
                }

            _price_cache[cache_key] = result
            _price_cache[cache_key]["_cached_at"] = datetime.utcnow()
            return result

    except Exception as e:
        print(f"CoinGecko error: {e}")
        return None


async def get_asset_price(asset) -> Optional[Dict]:
    """Universal price fetcher — routes to correct API based on asset.api_source"""
    if asset.api_source == "twelvedata":
        return await fetch_stock_price(asset.symbol)
    elif asset.api_source == "coingecko":
        all_crypto = await fetch_all_crypto_prices()
        if all_crypto and asset.coingecko_id:
            return all_crypto.get(asset.coingecko_id)
    return None