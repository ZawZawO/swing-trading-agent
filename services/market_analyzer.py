"""
Market Analyzer Service
=======================
Analyses broad market conditions using SPY and QQQ.

Logic:
  - Fetch latest daily prices for SPY and QQQ
  - Calculate EMA 50 on daily closes
  - If BOTH above EMA50  → Bullish
  - If ONE above EMA50   → Neutral
  - If NEITHER above     → Bearish

Returns a market_overview dict for display in the dashboard header.
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from services.data_fetcher import fetch_ohlcv, get_cached, set_cached
from services.indicator_engine import calc_ema

logger = logging.getLogger("market_analyzer")

_MARKET_TICKERS = ["SPY", "QQQ"]
_CACHE_KEY = "__market_overview__"


def _get_ticker_data(ticker: str) -> dict | None:
    """Fetch and analyse a single market index ticker."""
    try:
        df = fetch_ohlcv(ticker, interval="1d", days=120)
        if df is None or df.empty or len(df) < 50:
            return None

        close = df["Close"]
        ema50 = calc_ema(close, 50)
        price = round(float(close.iloc[-1]), 2)
        ema50_val = round(float(ema50.iloc[-1]), 2)

        pct_vs_ema = round((price - ema50_val) / ema50_val * 100, 2) if ema50_val > 0 else 0.0
        above = price > ema50_val

        # 5-day change
        price_5d = float(close.iloc[-6]) if len(close) > 5 else price
        change_5d = round((price - price_5d) / price_5d * 100, 2) if price_5d > 0 else 0.0

        return {
            "ticker": ticker,
            "price": price,
            "ema50": ema50_val,
            "above_ema50": above,
            "pct_vs_ema50": pct_vs_ema,
            "change_5d": change_5d,
        }
    except Exception as e:
        logger.warning(f"[MARKET] {ticker}: {e}")
        return None


def get_market_overview() -> dict:
    """
    Return market sentiment based on SPY and QQQ vs EMA50.
    Result is cached for 10 minutes.
    """
    indices = {}
    above_count = 0

    for ticker in _MARKET_TICKERS:
        info = _get_ticker_data(ticker)
        if info:
            indices[ticker] = info
            if info["above_ema50"]:
                above_count += 1

    # Determine overall sentiment
    if above_count == len(_MARKET_TICKERS):
        sentiment = "Bullish"
        sentiment_class = "bullish"
    elif above_count == 0:
        sentiment = "Bearish"
        sentiment_class = "bearish"
    else:
        sentiment = "Neutral"
        sentiment_class = "neutral"

    return {
        "sentiment": sentiment,
        "sentiment_class": sentiment_class,
        "indices": indices,
        "above_ema50": above_count,
        "total": len(_MARKET_TICKERS),
        "timestamp": datetime.now().isoformat(),
    }
