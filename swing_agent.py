"""
Swing Trading Agent - Multi-Signal Scanner
============================================
Scans stocks using hourly candles over a 2-month lookback.
Designed for 2-4 week hold periods.

Signals: EMA crossover, RSI, MACD, Volume, Support/Resistance
Output: BUY / SELL / HOLD with entry, stop-loss, target prices

Usage:
    python swing_agent.py                  # Scan default watchlist
    python swing_agent.py AAPL MSFT TSLA   # Scan specific stocks
    python swing_agent.py --top 5          # Show only top 5 signals
    python swing_agent.py --detail AAPL    # Deep analysis for one stock
"""

import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "watchlist": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD",
        "NFLX", "SPY", "QQQ", "SOFI", "PLTR", "COIN", "MARA", "SQ",
        "ROKU", "SNAP", "UBER", "SHOP"
    ],
    "lookback_days": 60,
    "interval": "1h",
    "ema_fast": 8,
    "ema_slow": 21,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_spike_multiplier": 1.5,
    "risk_percent": 2.0,
    "account_size": 10000,
    "min_score": 40,
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            user_cfg = json.load(f)
        cfg = {**DEFAULT_CONFIG, **user_cfg}
    else:
        cfg = DEFAULT_CONFIG.copy()
    return cfg


# ─── Technical Indicators ────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def find_support_resistance(df, window=20):
    highs = df["High"].rolling(window=window, center=True).max()
    lows = df["Low"].rolling(window=window, center=True).min()

    resistance_levels = []
    support_levels = []

    for i in range(window, len(df) - window):
        if df["High"].iloc[i] == highs.iloc[i]:
            resistance_levels.append(df["High"].iloc[i])
        if df["Low"].iloc[i] == lows.iloc[i]:
            support_levels.append(df["Low"].iloc[i])

    # Cluster nearby levels (within 1%)
    resistance = _cluster_levels(resistance_levels)
    support = _cluster_levels(support_levels)

    return support, resistance


def _cluster_levels(levels, threshold=0.01):
    if not levels:
        return []
    levels = sorted(levels)
    clusters = [[levels[0]]]
    for lvl in levels[1:]:
        if (lvl - clusters[-1][-1]) / clusters[-1][-1] < threshold:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    return [round(np.mean(c), 2) for c in clusters]


# ─── Signal Scoring Engine ───────────────────────────────────────────────────

def analyze_stock(ticker, cfg):
    """Analyze a single stock and return signal data."""
    try:
        end = datetime.now()
        start = end - timedelta(days=cfg["lookback_days"])

        stock = yf.Ticker(ticker)
        df = stock.history(start=start, end=end, interval=cfg["interval"])

        if df.empty or len(df) < 50:
            return None

        close = df["Close"]
        volume = df["Volume"]

        # --- Calculate indicators ---
        ema_fast = calc_ema(close, cfg["ema_fast"])
        ema_slow = calc_ema(close, cfg["ema_slow"])
        rsi = calc_rsi(close, cfg["rsi_period"])
        macd_line, signal_line, macd_hist = calc_macd(
            close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
        )
        avg_volume = volume.rolling(window=20).mean()
        support, resistance = find_support_resistance(df)

        # Latest values
        price = round(close.iloc[-1], 2)
        ema_f = round(ema_fast.iloc[-1], 2)
        ema_s = round(ema_slow.iloc[-1], 2)
        rsi_val = round(rsi.iloc[-1], 2)
        macd_val = round(macd_line.iloc[-1], 4)
        macd_sig = round(signal_line.iloc[-1], 4)
        macd_h = round(macd_hist.iloc[-1], 4)
        vol_now = volume.iloc[-1]
        vol_avg = avg_volume.iloc[-1]
        vol_ratio = round(vol_now / vol_avg, 2) if vol_avg > 0 else 0

        # Previous values for crossover detection
        ema_f_prev = ema_fast.iloc[-2]
        ema_s_prev = ema_slow.iloc[-2]
        macd_prev = macd_line.iloc[-2]
        macd_sig_prev = signal_line.iloc[-2]

        # --- Score calculation (0-100) ---
        score = 50  # neutral base
        reasons = []

        # EMA Crossover (+/- 20 points)
        if ema_f > ema_s and ema_f_prev <= ema_s_prev:
            score += 20
            reasons.append("EMA 8/21 bullish crossover (fresh)")
        elif ema_f > ema_s:
            score += 10
            reasons.append("Price above EMA 8 > EMA 21 (bullish trend)")
        elif ema_f < ema_s and ema_f_prev >= ema_s_prev:
            score -= 20
            reasons.append("EMA 8/21 bearish crossover (fresh)")
        elif ema_f < ema_s:
            score -= 10
            reasons.append("Price below EMA 8 < EMA 21 (bearish trend)")

        # RSI (+/- 15 points)
        if rsi_val < 30:
            score += 15
            reasons.append(f"RSI oversold at {rsi_val} (bounce potential)")
        elif rsi_val < 40:
            score += 8
            reasons.append(f"RSI approaching oversold at {rsi_val}")
        elif rsi_val > 70:
            score -= 15
            reasons.append(f"RSI overbought at {rsi_val} (pullback risk)")
        elif rsi_val > 60:
            score -= 5
            reasons.append(f"RSI elevated at {rsi_val}")
        else:
            reasons.append(f"RSI neutral at {rsi_val}")

        # MACD (+/- 15 points)
        if macd_val > macd_sig and macd_prev <= macd_sig_prev:
            score += 15
            reasons.append("MACD bullish crossover (fresh)")
        elif macd_val > macd_sig and macd_h > 0:
            score += 8
            reasons.append("MACD bullish with rising histogram")
        elif macd_val < macd_sig and macd_prev >= macd_sig_prev:
            score -= 15
            reasons.append("MACD bearish crossover (fresh)")
        elif macd_val < macd_sig:
            score -= 8
            reasons.append("MACD bearish")

        # Volume (+/- 10 points)
        if vol_ratio >= cfg["volume_spike_multiplier"]:
            if score > 50:
                score += 10
                reasons.append(f"Volume spike {vol_ratio}x confirms bullish move")
            else:
                score -= 5
                reasons.append(f"Volume spike {vol_ratio}x on bearish move")
        else:
            reasons.append(f"Volume ratio {vol_ratio}x (normal)")

        # Support/Resistance proximity (+/- 10 points)
        nearest_support = None
        nearest_resistance = None
        for s in sorted(support, reverse=True):
            if s < price:
                nearest_support = s
                break
        for r in sorted(resistance):
            if r > price:
                nearest_resistance = r
                break

        if nearest_support and (price - nearest_support) / price < 0.02:
            score += 10
            reasons.append(f"Near support ${nearest_support} (bounce zone)")
        if nearest_resistance and (nearest_resistance - price) / price < 0.02:
            score -= 5
            reasons.append(f"Near resistance ${nearest_resistance} (ceiling)")

        # Clamp score
        score = max(0, min(100, score))

        # --- Determine signal ---
        if score >= 70:
            signal = "STRONG BUY"
        elif score >= 60:
            signal = "BUY"
        elif score >= 40:
            signal = "HOLD"
        elif score >= 30:
            signal = "SELL"
        else:
            signal = "STRONG SELL"

        # --- Calculate trade levels ---
        if nearest_support:
            stop_loss = round(nearest_support * 0.99, 2)
        else:
            stop_loss = round(price * 0.95, 2)

        if nearest_resistance:
            target = round(nearest_resistance * 0.99, 2)
        else:
            target = round(price * 1.10, 2)

        risk_per_share = price - stop_loss
        reward_per_share = target - price
        rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0

        # Position sizing
        risk_amount = cfg["account_size"] * (cfg["risk_percent"] / 100)
        shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
        position_value = round(shares * price, 2)

        # 2-month price change
        price_start = close.iloc[0]
        change_2m = round(((price - price_start) / price_start) * 100, 2)

        return {
            "ticker": ticker,
            "price": price,
            "signal": signal,
            "score": score,
            "change_2m": change_2m,
            "ema_fast": ema_f,
            "ema_slow": ema_s,
            "rsi": rsi_val,
            "macd": macd_val,
            "macd_signal": macd_sig,
            "macd_hist": macd_h,
            "volume_ratio": vol_ratio,
            "support": nearest_support,
            "resistance": nearest_resistance,
            "stop_loss": stop_loss,
            "target": target,
            "rr_ratio": rr_ratio,
            "shares": shares,
            "position_value": position_value,
            "reasons": reasons,
        }

    except Exception as e:
        print(f"  [!] Error analyzing {ticker}: {e}")
        return None


# ─── Display Functions ───────────────────────────────────────────────────────

def print_header():
    print()
    print("=" * 72)
    print("  SWING TRADING AGENT - Multi-Signal Scanner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Hourly Candles  |  2-Month Lookback")
    print("=" * 72)


def print_summary_table(results, top_n=None):
    # Sort by score descending
    results = sorted(results, key=lambda x: x["score"], reverse=True)
    if top_n:
        results = results[:top_n]

    print()
    print(f"  {'TICKER':<8} {'PRICE':>8} {'SIGNAL':<12} {'SCORE':>5} {'RSI':>6} "
          f"{'VOL':>5} {'2M%':>7} {'STOP':>8} {'TARGET':>8} {'R:R':>5}")
    print("  " + "-" * 68)

    for r in results:
        signal_color = r["signal"]
        print(f"  {r['ticker']:<8} {r['price']:>8.2f} {signal_color:<12} {r['score']:>5} "
              f"{r['rsi']:>6.1f} {r['volume_ratio']:>4.1f}x {r['change_2m']:>+6.1f}% "
              f"{r['stop_loss']:>8.2f} {r['target']:>8.2f} {r['rr_ratio']:>4.1f}R")

    print()
    buys = [r for r in results if "BUY" in r["signal"]]
    sells = [r for r in results if "SELL" in r["signal"]]
    holds = [r for r in results if r["signal"] == "HOLD"]
    print(f"  Summary: {len(buys)} BUY  |  {len(holds)} HOLD  |  {len(sells)} SELL")


def print_detail(r, cfg):
    print()
    print(f"  {'=' * 50}")
    print(f"  DETAILED ANALYSIS: {r['ticker']}")
    print(f"  {'=' * 50}")
    print()
    print(f"  Price:          ${r['price']}")
    print(f"  Signal:         {r['signal']}  (Score: {r['score']}/100)")
    print(f"  2-Month Change: {r['change_2m']:+.1f}%")
    print()
    print(f"  --- Indicators ---")
    print(f"  EMA {cfg['ema_fast']}:        ${r['ema_fast']}")
    print(f"  EMA {cfg['ema_slow']}:       ${r['ema_slow']}")
    print(f"  RSI ({cfg['rsi_period']}):      {r['rsi']}")
    print(f"  MACD:           {r['macd']}")
    print(f"  MACD Signal:    {r['macd_signal']}")
    print(f"  MACD Histogram: {r['macd_hist']}")
    print(f"  Volume Ratio:   {r['volume_ratio']}x avg")
    print()
    print(f"  --- Key Levels ---")
    print(f"  Support:        ${r['support'] or 'N/A'}")
    print(f"  Resistance:     ${r['resistance'] or 'N/A'}")
    print()
    print(f"  --- Trade Plan ---")
    print(f"  Entry:          ${r['price']}")
    print(f"  Stop Loss:      ${r['stop_loss']}")
    print(f"  Target:         ${r['target']}")
    print(f"  Risk/Reward:    1:{r['rr_ratio']}")
    print(f"  Position Size:  {r['shares']} shares (${r['position_value']})")
    print(f"  Risk Amount:    ${round(cfg['account_size'] * cfg['risk_percent'] / 100, 2)}"
          f"  ({cfg['risk_percent']}% of ${cfg['account_size']})")
    print()
    print(f"  --- Signal Reasons ---")
    for reason in r["reasons"]:
        print(f"    * {reason}")
    print()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Swing Trading Agent")
    parser.add_argument("tickers", nargs="*", help="Stock tickers to scan")
    parser.add_argument("--top", type=int, help="Show only top N results")
    parser.add_argument("--detail", type=str, help="Show detailed analysis for one ticker")
    parser.add_argument("--min-score", type=int, help="Minimum signal score to display")
    parser.add_argument("--export", type=str, help="Export results to CSV file")
    args = parser.parse_args()

    cfg = load_config()

    print_header()

    # Determine tickers to scan
    if args.detail:
        tickers = [args.detail.upper()]
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = cfg["watchlist"]

    min_score = args.min_score if args.min_score is not None else cfg["min_score"]

    print(f"\n  Scanning {len(tickers)} stocks...\n")

    results = []
    for i, ticker in enumerate(tickers):
        pct = int((i + 1) / len(tickers) * 100)
        print(f"\r  [{pct:>3}%] Analyzing {ticker}...", end="", flush=True)
        result = analyze_stock(ticker, cfg)
        if result and result["score"] >= min_score:
            results.append(result)

    print(f"\r  [100%] Done! {len(results)} stocks passed score filter (>= {min_score})    ")

    if not results:
        print("\n  No stocks matched the criteria. Try lowering --min-score.")
        return

    if args.detail:
        print_detail(results[0], cfg)
    else:
        print_summary_table(results, args.top)

    # Export to CSV
    if args.export and results:
        df = pd.DataFrame(results)
        df = df.drop(columns=["reasons"])
        df.to_csv(args.export, index=False)
        print(f"  Exported to {args.export}")

    # Show top picks
    top_buys = [r for r in results if "BUY" in r["signal"]]
    if top_buys and not args.detail:
        top_buys = sorted(top_buys, key=lambda x: x["score"], reverse=True)[:3]
        print("\n  TOP PICKS:")
        for r in top_buys:
            print(f"    >> {r['ticker']} @ ${r['price']}  |  Score: {r['score']}  |  "
                  f"Target: ${r['target']}  |  Stop: ${r['stop_loss']}  |  R:R 1:{r['rr_ratio']}")
        print()


if __name__ == "__main__":
    main()
