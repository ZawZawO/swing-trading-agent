"""
Data Fetcher Service
====================
Multi-source OHLCV fetching with automatic fallback, caching (10-min TTL),
retry logic with exponential backoff, and rate-limit protection.

Priority: Polygon.io → Alpha Vantage → Yahoo Finance (always available)
"""
import time
import logging
import threading
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

from services.error_monitor import log_api_error

logger = logging.getLogger("data_fetcher")

# ─── In-memory cache ─────────────────────────────────────────────────────────
_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 600  # 10 minutes


def _cache_key(ticker: str, interval: str, days: int) -> str:
    return f"{ticker}|{interval}|{days}"


def get_cached(ticker: str, interval: str, days: int):
    key = _cache_key(ticker, interval, days)
    with _cache_lock:
        entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        logger.debug(f"[CACHE HIT] {ticker} {interval}")
        return entry["data"]
    return None


def set_cached(ticker: str, interval: str, days: int, data: pd.DataFrame):
    key = _cache_key(ticker, interval, days)
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time()}


def clear_cache(ticker: str = None):
    """Clear cache for a specific ticker or entirely."""
    with _cache_lock:
        if ticker:
            keys = [k for k in _cache if k.startswith(f"{ticker}|")]
            for k in keys:
                del _cache[k]
        else:
            _cache.clear()


# ─── Source fetchers ─────────────────────────────────────────────────────────

def _fetch_yahoo(ticker: str, interval: str, days: int) -> pd.DataFrame | None:
    """Fetch OHLCV from Yahoo Finance."""
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, interval=interval)
        if not df.empty and len(df) >= 10:
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df = df.dropna(subset=["Close"])
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
    except Exception as e:
        log_api_error("yahoo", ticker, str(e))
        logger.warning(f"[YAHOO] {ticker}: {e}")
    return None


def _fetch_polygon(ticker: str, interval: str, days: int, api_key: str) -> pd.DataFrame | None:
    """Fetch OHLCV from Polygon.io."""
    try:
        span_map = {"1h": ("1", "hour"), "1d": ("1", "day"), "4h": ("4", "hour")}
        mult, span = span_map.get(interval, ("1", "hour"))
        end = datetime.now()
        start = end - timedelta(days=days)
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range"
            f"/{mult}/{span}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        )
        params = {"apiKey": api_key, "limit": 50000, "adjusted": "true", "sort": "asc"}
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            logger.warning("[POLYGON] Rate limited – sleeping 60s")
            time.sleep(60)
            raise Exception("Rate limited by Polygon")
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        df = pd.DataFrame(results)
        df.index = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    except Exception as e:
        log_api_error("polygon", ticker, str(e))
        logger.warning(f"[POLYGON] {ticker}: {e}")
        return None


def _fetch_alpha_vantage(ticker: str, interval: str, days: int, api_key: str) -> pd.DataFrame | None:
    """Fetch OHLCV from Alpha Vantage."""
    try:
        av_interval = {"1h": "60min", "1d": "daily"}.get(interval, "60min")
        if av_interval == "daily":
            function = "TIME_SERIES_DAILY_ADJUSTED"
            ts_key = "Time Series (Daily)"
            close_col = "4. adjusted close"
        else:
            function = "TIME_SERIES_INTRADAY"
            ts_key = f"Time Series ({av_interval})"
            close_col = "4. close"
        params = {"function": function, "symbol": ticker, "apikey": api_key, "outputsize": "full"}
        if function == "TIME_SERIES_INTRADAY":
            params["interval"] = av_interval
        resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # Alpha Vantage rate limit message
        if "Note" in data or "Information" in data:
            raise Exception(data.get("Note", data.get("Information", "Rate limited")))
        ts = data.get(ts_key, {})
        if not ts:
            return None
        cutoff = datetime.now() - timedelta(days=days)
        records = []
        for date_str, vals in ts.items():
            dt = pd.to_datetime(date_str)
            dt_naive = dt.tz_localize(None) if getattr(dt, "tzinfo", None) else dt
            if dt_naive < cutoff:
                continue
            try:
                records.append({
                    "ts": dt_naive,
                    "Open": float(vals.get("1. open", 0)),
                    "High": float(vals.get("2. high", 0)),
                    "Low": float(vals.get("3. low", 0)),
                    "Close": float(vals.get(close_col, 0)),
                    "Volume": float(vals.get("5. volume", vals.get("6. volume", 0))),
                })
            except Exception:
                pass
        if not records:
            return None
        df = pd.DataFrame(records).set_index("ts").sort_index()
        return df.dropna(subset=["Close"])
    except Exception as e:
        log_api_error("alpha_vantage", ticker, str(e))
        logger.warning(f"[ALPHA_VANTAGE] {ticker}: {e}")
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_ohlcv(
    ticker: str,
    interval: str = "1h",
    days: int = 90,
    polygon_key: str = None,
    alpha_key: str = None,
) -> pd.DataFrame | None:
    """
    Fetch OHLCV data with:
      1. In-memory cache (10-min TTL)
      2. Primary: Polygon.io (if polygon_key set)
      3. Fallback: Alpha Vantage (if alpha_key set)
      4. Backup: Yahoo Finance (up to 3 retries with exponential backoff)
    """
    # Check cache first
    cached = get_cached(ticker, interval, days)
    if cached is not None:
        return cached

    data = None
    source = None

    # Primary: Polygon
    if polygon_key:
        data = _fetch_polygon(ticker, interval, days, polygon_key)
        if data is not None and not data.empty:
            source = "Polygon.io"

    # Fallback: Alpha Vantage
    if data is None and alpha_key:
        data = _fetch_alpha_vantage(ticker, interval, days, alpha_key)
        if data is not None and not data.empty:
            source = "Alpha Vantage"

    # Backup: Yahoo Finance (3 retries)
    if data is None:
        for attempt in range(3):
            data = _fetch_yahoo(ticker, interval, days)
            if data is not None and not data.empty:
                source = "Yahoo Finance"
                break
            backoff = 2 ** attempt
            logger.warning(f"[YAHOO] retry {attempt + 1}/3 for {ticker} in {backoff}s")
            time.sleep(backoff)

    if data is not None and not data.empty:
        logger.info(f"[FETCH] {ticker} via {source} ({len(data)} bars)")
        set_cached(ticker, interval, days, data)
        return data

    logger.error(f"[FETCH] All sources failed for {ticker}")
    return None
