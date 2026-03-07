"""
Indicator Engine Service
========================
Calculates all technical indicators on OHLCV DataFrames.
All functions return pandas Series aligned to the input index.

Indicators:
  EMA 20, EMA 50, RSI 14, MACD (12/26/9), Average Volume (20), ATR 14
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger("indicator_engine")


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI using EWM smoothing."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, histogram."""
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's method)."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - prev_close).abs(),
        "lc": (low - prev_close).abs(),
    }).max(axis=1)
    # Use EWM (Wilder's) for ATR
    return tr.ewm(com=period - 1, min_periods=period, adjust=False).mean()


def calc_avg_volume(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple rolling average volume."""
    return series.rolling(window=period, min_periods=1).mean()


def calc_all(df: pd.DataFrame, ticker: str = "") -> dict:
    """
    Calculate all indicators and return as a dict of Series.
    Required columns: Open, High, Low, Close, Volume
    """
    label = f"[{ticker}] " if ticker else ""
    logger.info(f"{label}Calculating indicators on {len(df)} bars")

    close = df["Close"]
    volume = df["Volume"]

    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    logger.debug(f"{label}EMA20={ema20.iloc[-1]:.4f}  EMA50={ema50.iloc[-1]:.4f}")

    rsi = calc_rsi(close, 14)
    logger.debug(f"{label}RSI={rsi.iloc[-1]:.2f}")

    macd_line, macd_signal, macd_hist = calc_macd(close)
    logger.debug(f"{label}MACD={macd_line.iloc[-1]:.4f}  Signal={macd_signal.iloc[-1]:.4f}")

    avg_vol = calc_avg_volume(volume, 20)
    atr = calc_atr(df, 14)
    logger.debug(f"{label}ATR={atr.iloc[-1]:.4f}  AvgVol={avg_vol.iloc[-1]:.0f}")

    logger.info(f"{label}Indicators loaded: EMA20/50, RSI, MACD, ATR, AvgVolume")

    return {
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "avg_volume": avg_vol,
        "atr": atr,
    }


def get_latest(indicators: dict) -> dict:
    """Extract latest scalar values from indicator series dict."""
    def safe(series, default=0.0):
        try:
            v = series.iloc[-1]
            return float(v) if pd.notna(v) else default
        except Exception:
            return default

    def safe2(series, default=0.0):
        try:
            v = series.iloc[-2]
            return float(v) if pd.notna(v) else default
        except Exception:
            return default

    return {
        "ema20": safe(indicators["ema20"]),
        "ema50": safe(indicators["ema50"]),
        "ema20_prev": safe2(indicators["ema20"]),
        "ema50_prev": safe2(indicators["ema50"]),
        "rsi": safe(indicators["rsi"], 50.0),
        "macd": safe(indicators["macd_line"]),
        "macd_sig": safe(indicators["macd_signal"]),
        "macd_hist": safe(indicators["macd_hist"]),
        "macd_prev": safe2(indicators["macd_line"]),
        "macd_sig_prev": safe2(indicators["macd_signal"]),
        "avg_volume": safe(indicators["avg_volume"], 1.0),
        "atr": safe(indicators["atr"]),
    }
