"""
Scoring Engine Service
======================
Calculates the AI SwingScore (0-100) using four normalised components:

  trend_strength     × 0.30  — EMA20/EMA50 divergence normalised to 0-1
  volume_confirmation × 0.20  — current volume vs 20-bar average, 0-1
  momentum_score     × 0.20  — RSI-based momentum, 0-1
  win_rate           × 0.30  — historical setup win rate, 0-1

  SwingScore = sum(weighted components) × 100
"""
import numpy as np
import pandas as pd

from services.error_monitor import log_score


# ─── Component Calculators ───────────────────────────────────────────────────

def calc_trend_strength(ema20: float, ema50: float, price: float) -> float:
    """
    Measures how far EMA20 is above/below EMA50 relative to price.
    Normalised to 0-1 using a ±3% price-relative band as bounds.
    0.0 = EMA20 deeply below EMA50 (bearish)
    0.5 = EMAs flat
    1.0 = EMA20 well above EMA50 (bullish)
    """
    if price <= 0:
        return 0.5
    raw = (ema20 - ema50) / price
    # Typical swing-trading band: ±0.03 (3% of price)
    normalised = (raw + 0.03) / 0.06
    return max(0.0, min(1.0, normalised))


def calc_momentum_score(rsi: float) -> float:
    """
    RSI-based momentum normalised to 0-1.
    RSI > 60 → 1.0 (strong momentum)
    RSI 45-60 → 0.5 (neutral, scales linearly)
    RSI < 45  → 0.0 (pullback)
    """
    if rsi >= 60:
        return 1.0
    elif rsi >= 45:
        return (rsi - 45) / 15  # 0 → 1 over 45-60 range
    else:
        return max(0.0, rsi / 90)  # small non-zero value for deep oversold


def calc_volume_confirmation(current_volume: float, avg_volume: float) -> float:
    """
    Volume ratio normalised to 0-1.
    current_volume / avg_volume: 0.5x → 0.0, 1x → 0.33, 2x → 0.67, 3x+ → 1.0
    """
    if avg_volume <= 0:
        return 0.33
    ratio = current_volume / avg_volume
    # Cap at 3x, floor at 0x
    return max(0.0, min(1.0, ratio / 3.0))


# ─── Win Rate via Historical Simulation ──────────────────────────────────────

def calc_win_rate(
    df: pd.DataFrame,
    setup_type: str,
    ema20_series: pd.Series,
    ema50_series: pd.Series,
    rsi_series: pd.Series,
    avg_vol_series: pd.Series,
) -> float:
    """
    Simulate historical occurrences of the same setup over the full dataset.
    For each occurrence, check if price rose after ~10 trading days (65 hourly bars).
    Returns win_rate as 0-1 (defaults to 0.50 if no signals found).
    """
    hold_bars = 65  # ~10 trading days on hourly data
    min_idx = 50    # need at least 50 bars of indicator warmup

    if len(df) < hold_bars + min_idx + 5:
        return 0.5

    close = df["Close"]
    volume = df["Volume"]
    highs = df["High"]
    lows = df["Low"]

    wins = 0
    total = 0

    for i in range(min_idx, len(df) - hold_bars):
        try:
            price_i = float(close.iloc[i])
            ema20_i = float(ema20_series.iloc[i]) if pd.notna(ema20_series.iloc[i]) else None
            ema50_i = float(ema50_series.iloc[i]) if pd.notna(ema50_series.iloc[i]) else None
            rsi_i = float(rsi_series.iloc[i]) if pd.notna(rsi_series.iloc[i]) else None
            avol_i = float(avg_vol_series.iloc[i]) if pd.notna(avg_vol_series.iloc[i]) else None
            vol_i = float(volume.iloc[i])

            if None in (ema20_i, ema50_i, rsi_i, avol_i) or price_i <= 0:
                continue

            triggered = False
            if setup_type == "Pullback":
                if (price_i > ema50_i
                        and ema20_i > 0
                        and abs(price_i - ema20_i) / price_i < 0.03
                        and rsi_i < 45):
                    triggered = True

            elif setup_type == "Breakout":
                if i >= 20:
                    res_level = float(highs.iloc[i - 20:i].max())
                    if price_i > res_level and vol_i > avol_i:
                        triggered = True

            elif setup_type == "Range Break":
                lookback = min(65, i)
                if lookback >= 20:
                    r_high = float(highs.iloc[i - lookback:i].max())
                    r_low = float(lows.iloc[i - lookback:i].min())
                    if r_low > 0:
                        rng = (r_high - r_low) / r_low
                        if rng < 0.07 and price_i > r_high:
                            triggered = True

            if triggered:
                future_price = float(close.iloc[i + hold_bars])
                total += 1
                if future_price > price_i:
                    wins += 1
        except Exception:
            continue

    if total == 0:
        return 0.5
    return round(wins / total, 4)


# ─── Master SwingScore ────────────────────────────────────────────────────────

def calc_swing_score(
    ticker: str,
    price: float,
    ema20: float,
    ema50: float,
    rsi: float,
    current_volume: float,
    avg_volume: float,
    win_rate: float,
) -> tuple[float, dict]:
    """
    Calculate final SwingScore (0-100) and return component breakdown.

    Returns (swing_score, components_dict)
    """
    trend = calc_trend_strength(ema20, ema50, price)
    momentum = calc_momentum_score(rsi)
    volume = calc_volume_confirmation(current_volume, avg_volume)

    components = {
        "trend_strength": round(trend, 4),
        "momentum_score": round(momentum, 4),
        "volume_confirmation": round(volume, 4),
        "win_rate": round(win_rate, 4),
    }

    raw = (
        trend   * 0.30
        + volume * 0.20
        + momentum * 0.20
        + win_rate * 0.30
    )
    swing_score = round(raw * 100, 1)
    swing_score = max(0.0, min(100.0, swing_score))

    log_score(ticker, swing_score, components)
    return swing_score, components
