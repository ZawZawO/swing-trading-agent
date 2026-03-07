"""
Setup Detector Service
======================
Detects three swing trading setup patterns:

  Pullback   – price > EMA50, near EMA20, RSI < 45
  Breakout   – price > resistance level, volume > average volume
  Range Break – price breaks above a tight 10-day range

Also provides support/resistance detection via swing-high/low clustering.
"""
import numpy as np
import pandas as pd


# ─── Support / Resistance ─────────────────────────────────────────────────────

def _cluster_levels(levels: list[float], threshold: float = 0.015) -> list[float]:
    """Merge nearby price levels within threshold %."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = [[levels[0]]]
    for lvl in levels[1:]:
        if lvl > 0 and (lvl - clusters[-1][-1]) / clusters[-1][-1] < threshold:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    return [round(float(np.mean(c)), 2) for c in clusters]


def find_support_resistance(df: pd.DataFrame, window: int = 20) -> tuple[list, list]:
    """
    Detect support and resistance via rolling swing high/low.
    Returns (support_levels, resistance_levels) as clustered lists.
    """
    if len(df) < window * 2:
        return [], []

    highs = df["High"].rolling(window=window, center=True).max()
    lows = df["Low"].rolling(window=window, center=True).min()

    res_raw, sup_raw = [], []
    for i in range(window, len(df) - window):
        if pd.notna(highs.iloc[i]) and df["High"].iloc[i] == highs.iloc[i]:
            res_raw.append(float(df["High"].iloc[i]))
        if pd.notna(lows.iloc[i]) and df["Low"].iloc[i] == lows.iloc[i]:
            sup_raw.append(float(df["Low"].iloc[i]))

    return _cluster_levels(sup_raw), _cluster_levels(res_raw)


def nearest_support(price: float, support_levels: list[float]) -> float | None:
    """Return the nearest support level below current price."""
    below = [s for s in support_levels if s < price]
    return max(below) if below else None


def nearest_resistance(price: float, resistance_levels: list[float]) -> float | None:
    """Return the nearest resistance level above current price."""
    above = [r for r in resistance_levels if r > price]
    return min(above) if above else None


# ─── Setup Detection ─────────────────────────────────────────────────────────

def detect_setup(
    df: pd.DataFrame,
    price: float,
    ema20: float,
    ema50: float,
    rsi: float,
    avg_volume: float,
    resistance_level: float | None,
) -> str:
    """
    Detect which swing setup is active for this stock.

    Returns one of: 'Pullback', 'Breakout', 'Range Break', 'Neutral'
    """
    try:
        current_volume = float(df["Volume"].iloc[-1])
    except Exception:
        current_volume = 0

    # ── Pullback ─────────────────────────────────────────────────────────────
    # price > EMA50, price near EMA20 (within 3%), RSI < 45
    if (
        price > ema50
        and ema20 > 0
        and abs(price - ema20) / price < 0.03
        and rsi < 45
    ):
        return "Pullback"

    # ── Breakout ─────────────────────────────────────────────────────────────
    # price > resistance level AND volume > average volume
    if (
        resistance_level is not None
        and price > resistance_level
        and avg_volume > 0
        and current_volume > avg_volume
    ):
        return "Breakout"

    # ── Range Break ──────────────────────────────────────────────────────────
    # price traded in a tight range for 10+ days, now breaking above range high
    # 10 trading days ≈ 65 hourly bars
    lookback = min(65, len(df) - 1)
    if lookback >= 20:
        try:
            window_df = df.iloc[-lookback - 1 : -1]
            range_high = float(window_df["High"].max())
            range_low = float(window_df["Low"].min())
            if range_low > 0:
                range_size_pct = (range_high - range_low) / range_low
                # "Tight range" = less than 7% swing, break above range high
                if range_size_pct < 0.07 and price > range_high:
                    return "Range Break"
        except Exception:
            pass

    return "Neutral"
