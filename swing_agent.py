"""
Swing Trading Agent - AI Multi-Signal Scanner
===============================================
Scans stocks using hourly candles over a 3-month lookback.
Designed for 2-4 week hold periods.

Architecture: modular services
  data_fetcher    → multi-source OHLCV with caching
  indicator_engine → EMA 20/50, RSI, MACD, ATR, Volume
  setup_detector  → Pullback / Breakout / Range Break
  scoring_engine  → AI SwingScore (0-100)
  risk_manager    → ATR-based stops, position sizing

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

import pandas as pd
import numpy as np

# ─── Configuration ────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "watchlist": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD",
        "NFLX", "SPY", "QQQ", "SOFI", "PLTR", "COIN", "MARA",
        "ROKU", "SNAP", "UBER", "SHOP", "HOOD",
    ],
    "lookback_days": 90,
    "interval": "1h",
    "ema_fast": 20,
    "ema_slow": 50,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_spike_multiplier": 1.5,
    "risk_percent": 3.0,
    "account_size": 300,
    "min_score": 30,
    "polygon_key": "",
    "alpha_key": "",
    "auto_refresh_minutes": 5,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_cfg = json.load(f)
        return {**DEFAULT_CONFIG, **user_cfg}
    return DEFAULT_CONFIG.copy()


# ─── Indicator helpers (kept for backward-compat with app.py chart routes) ───

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def find_support_resistance(df: pd.DataFrame, window: int = 20):
    """Wrapper used by app.py chart routes."""
    from services.setup_detector import find_support_resistance as _sr
    return _sr(df, window)


# ─── LookForward Projection Engine ───────────────────────────────────────────

LOOKFORWARD_HORIZONS = {"1W": 5, "2W": 10, "3W": 15, "1M": 21, "2M": 42, "3M": 63}
BARS_PER_DAY = 6.5


def calc_lookforward(df: pd.DataFrame, price: float, score: float) -> dict:
    """GBM-based price projections for 6 forward horizons."""
    close = df["Close"]
    daily_close = close.resample("1D").last().dropna()
    if len(daily_close) < 5:
        daily_log_ret = np.log(close / close.shift(1)).dropna() * np.sqrt(BARS_PER_DAY)
    else:
        daily_log_ret = np.log(daily_close / daily_close.shift(1)).dropna()

    window = min(30, len(daily_log_ret))
    mu = daily_log_ret.iloc[-window:].mean()
    vol = daily_log_ret.iloc[-window:].std()
    bias = (score - 50) / 50 * 0.0005
    mu += bias

    projections = {}
    for label, days in LOOKFORWARD_HORIZONS.items():
        base = round(price * np.exp(mu * days), 2)
        bull = round(price * np.exp((mu + vol) * days), 2)
        bear = round(price * np.exp((mu - vol) * days), 2)
        projections[label] = {
            "base": base, "bull": bull, "bear": bear,
            "base_pct": round((base - price) / price * 100, 1),
            "bull_pct": round((bull - price) / price * 100, 1),
            "bear_pct": round((bear - price) / price * 100, 1),
            "days": days,
        }
    return projections


# ─── Core AI Analysis ─────────────────────────────────────────────────────────

def analyze_stock(ticker: str, cfg: dict) -> dict | None:
    """
    Full AI analysis of a single stock.
    Returns a rich dict compatible with the dashboard frontend.
    """
    try:
        from services.data_fetcher import fetch_ohlcv
        from services.indicator_engine import calc_all, get_latest, calc_ema as svc_ema
        from services.setup_detector import (
            find_support_resistance, nearest_support, nearest_resistance, detect_setup
        )
        from services.scoring_engine import calc_win_rate, calc_swing_score
        from services.risk_manager import calc_trade_levels

        # ── Fetch data ────────────────────────────────────────────────────────
        df = fetch_ohlcv(
            ticker,
            interval=cfg.get("interval", "1h"),
            days=cfg.get("lookback_days", 90),
            polygon_key=cfg.get("polygon_key", "") or None,
            alpha_key=cfg.get("alpha_key", "") or None,
        )
        if df is None or df.empty or len(df) < 50:
            return None

        close = df["Close"]
        volume = df["Volume"]

        # ── Indicators ────────────────────────────────────────────────────────
        indicators = calc_all(df, ticker=ticker)
        lat = get_latest(indicators)

        price = round(float(close.iloc[-1]), 4)
        if price <= 0:
            return None

        ema20 = lat["ema20"]
        ema50 = lat["ema50"]
        rsi_val = lat["rsi"]
        macd_val = lat["macd"]
        macd_sig = lat["macd_sig"]
        macd_h = lat["macd_hist"]
        avg_vol = lat["avg_volume"]
        atr_val = lat["atr"]
        current_vol = float(volume.iloc[-1])
        vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0.0

        # Previous values for crossover detection
        ema20_prev = lat["ema20_prev"]
        ema50_prev = lat["ema50_prev"]
        macd_prev = lat["macd_prev"]
        macd_sig_prev = lat["macd_sig_prev"]

        # ── Support / Resistance ──────────────────────────────────────────────
        sup_levels, res_levels = find_support_resistance(df)
        sup = nearest_support(price, sup_levels)
        res = nearest_resistance(price, res_levels)

        # ── Setup Detection ───────────────────────────────────────────────────
        setup_type = detect_setup(df, price, ema20, ema50, rsi_val, avg_vol, res)

        # ── Win Rate (historical backtest) ────────────────────────────────────
        win_rate = calc_win_rate(
            df, setup_type,
            indicators["ema20"], indicators["ema50"],
            indicators["rsi"], indicators["avg_volume"],
        )

        # ── AI SwingScore ─────────────────────────────────────────────────────
        swing_score, components = calc_swing_score(
            ticker, price, ema20, ema50, rsi_val,
            current_vol, avg_vol, win_rate,
        )

        # ── Legacy score (0-100, used by chart/backtest routes) ───────────────
        legacy_score = _calc_legacy_score(
            ema20, ema50, ema20_prev, ema50_prev,
            rsi_val, macd_val, macd_sig, macd_h,
            macd_prev, macd_sig_prev, vol_ratio,
            cfg.get("volume_spike_multiplier", 1.5), sup, res, price,
        )

        # ── Trade Levels (ATR-based) ──────────────────────────────────────────
        levels = calc_trade_levels(
            price, atr_val,
            account_size=cfg.get("account_size", 300),
            risk_percent=cfg.get("risk_percent", 3.0),
        )

        # ── Signal label from legacy score ────────────────────────────────────
        if legacy_score >= 70:
            signal = "STRONG BUY"
        elif legacy_score >= 60:
            signal = "BUY"
        elif legacy_score >= 40:
            signal = "HOLD"
        elif legacy_score >= 30:
            signal = "SELL"
        else:
            signal = "STRONG SELL"

        # ── 2-month price change ──────────────────────────────────────────────
        price_start = float(close.iloc[0])
        change_2m = round((price - price_start) / price_start * 100, 2) if price_start > 0 else 0.0

        # ── LookForward ───────────────────────────────────────────────────────
        lookforward = calc_lookforward(df, price, swing_score)

        # ── Signal reasons ────────────────────────────────────────────────────
        reasons = _build_reasons(
            ema20, ema50, ema20_prev, ema50_prev,
            rsi_val, macd_val, macd_sig, macd_h,
            macd_prev, macd_sig_prev, vol_ratio,
            cfg.get("volume_spike_multiplier", 1.5),
            sup, res, price, setup_type,
        )

        return {
            # Identifiers
            "ticker": ticker,
            "price": round(price, 2),
            "signal": signal,
            # AI Scores
            "score": legacy_score,          # backward compat
            "swing_score": swing_score,     # new AI score
            "setup_type": setup_type,
            "win_rate": round(win_rate * 100, 1),
            "score_components": components,
            # Indicators
            "ema_fast": round(ema20, 2),    # ema_fast = EMA20
            "ema_slow": round(ema50, 2),    # ema_slow = EMA50
            "rsi": round(rsi_val, 2),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_sig, 4),
            "macd_hist": round(macd_h, 4),
            "atr": round(atr_val, 4),
            "volume_ratio": vol_ratio,
            "change_2m": change_2m,
            # Levels
            "support": sup,
            "resistance": res,
            "stop_loss": levels["stop_loss"],
            "target": levels["target"],
            "entry": levels["entry"],
            "rr_ratio": levels["rr_ratio"],
            "shares": levels["shares"],
            "position_value": levels["position_value"],
            "risk_amount": levels["risk_amount"],
            # Extras
            "reasons": reasons,
            "lookforward": lookforward,
        }

    except Exception as e:
        print(f"  [!] Error analysing {ticker}: {e}")
        return None


# ─── Legacy Scoring (for backward-compat with backtest/chart) ────────────────

def _calc_legacy_score(
    ema20, ema50, ema20_prev, ema50_prev,
    rsi_val, macd_val, macd_sig, macd_h,
    macd_prev, macd_sig_prev, vol_ratio, vol_mult,
    sup, res, price,
) -> int:
    score = 50
    if ema20 > ema50 and ema20_prev <= ema50_prev:
        score += 20
    elif ema20 > ema50:
        score += 10
    elif ema20 < ema50 and ema20_prev >= ema50_prev:
        score -= 20
    elif ema20 < ema50:
        score -= 10

    if rsi_val < 30:
        score += 15
    elif rsi_val < 40:
        score += 8
    elif rsi_val > 70:
        score -= 15
    elif rsi_val > 60:
        score -= 5

    if macd_val > macd_sig and macd_prev <= macd_sig_prev:
        score += 15
    elif macd_val > macd_sig and macd_h > 0:
        score += 8
    elif macd_val < macd_sig and macd_prev >= macd_sig_prev:
        score -= 15
    elif macd_val < macd_sig:
        score -= 8

    if vol_ratio >= vol_mult:
        score += 10 if score > 50 else -5

    if sup and price > 0 and (price - sup) / price < 0.02:
        score += 10
    if res and price > 0 and (res - price) / price < 0.02:
        score -= 5

    return max(0, min(100, score))


def _build_reasons(
    ema20, ema50, ema20_prev, ema50_prev,
    rsi_val, macd_val, macd_sig, macd_h,
    macd_prev, macd_sig_prev, vol_ratio, vol_mult,
    sup, res, price, setup_type,
) -> list[str]:
    reasons = []
    if ema20 > ema50 and ema20_prev <= ema50_prev:
        reasons.append("EMA 20/50 bullish crossover (fresh)")
    elif ema20 > ema50:
        reasons.append(f"EMA 20 (${ema20:.2f}) > EMA 50 (${ema50:.2f}) — bullish")
    elif ema20 < ema50 and ema20_prev >= ema50_prev:
        reasons.append("EMA 20/50 bearish crossover (fresh)")
    else:
        reasons.append(f"EMA 20 (${ema20:.2f}) < EMA 50 (${ema50:.2f}) — bearish")

    if rsi_val < 30:
        reasons.append(f"RSI {rsi_val:.1f} — oversold (bounce potential)")
    elif rsi_val < 45:
        reasons.append(f"RSI {rsi_val:.1f} — pullback zone")
    elif rsi_val > 70:
        reasons.append(f"RSI {rsi_val:.1f} — overbought (pullback risk)")
    elif rsi_val > 60:
        reasons.append(f"RSI {rsi_val:.1f} — strong momentum")
    else:
        reasons.append(f"RSI {rsi_val:.1f} — neutral")

    if macd_val > macd_sig and macd_prev <= macd_sig_prev:
        reasons.append("MACD bullish crossover (fresh)")
    elif macd_val > macd_sig:
        reasons.append("MACD bullish")
    elif macd_val < macd_sig and macd_prev >= macd_sig_prev:
        reasons.append("MACD bearish crossover (fresh)")
    else:
        reasons.append("MACD bearish")

    if vol_ratio >= vol_mult:
        reasons.append(f"Volume spike {vol_ratio:.1f}x avg — confirms move")
    else:
        reasons.append(f"Volume {vol_ratio:.1f}x avg — normal")

    if sup:
        reasons.append(f"Support: ${sup:.2f}")
    if res:
        reasons.append(f"Resistance: ${res:.2f}")

    reasons.append(f"Setup: {setup_type}")
    return reasons


# ─── CLI Display ──────────────────────────────────────────────────────────────

def print_header():
    horizons = "  |  ".join(LOOKFORWARD_HORIZONS.keys())
    print()
    print("=" * 90)
    print("  AI SWING TRADING ASSISTANT — Multi-Signal Scanner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Hourly Candles  |  "
          f"EMA 20/50  |  ATR Stops  |  LookForward: {horizons}")
    print("=" * 90)


def print_summary_table(results, top_n=None):
    if top_n:
        results = results[:top_n]
    print()
    print(f"  {'TICKER':<8} {'PRICE':>8} {'SETUP':<12} {'AI':>5} {'RSI':>6} "
          f"{'VOL':>5} {'2M%':>7} {'STOP':>8} {'TARGET':>8} {'R:R':>5}")
    print("  " + "-" * 72)
    for r in results:
        print(f"  {r['ticker']:<8} {r['price']:>8.2f} {r['setup_type']:<12} "
              f"{r['swing_score']:>5.1f} {r['rsi']:>6.1f} {r['volume_ratio']:>4.1f}x "
              f"{r['change_2m']:>+6.1f}% {r['stop_loss']:>8.2f} "
              f"{r['target']:>8.2f} {r['rr_ratio']:>4.1f}R")
    print()
    buys = [r for r in results if "BUY" in r["signal"]]
    sells = [r for r in results if "SELL" in r["signal"]]
    holds = [r for r in results if r["signal"] == "HOLD"]
    print(f"  Summary: {len(buys)} BUY  |  {len(holds)} HOLD  |  {len(sells)} SELL")


def print_lookforward_table(results):
    labels = list(LOOKFORWARD_HORIZONS.keys())
    col_w = 11
    print()
    print("  -- LOOKFORWARD PROJECTIONS (Base % per horizon) " + "-" * 36)
    print(f"  {'TICKER':<8}  {'PRICE':>8}  " + "".join(f"{l:>{col_w}}" for l in labels))
    print("  " + "-" * (18 + col_w * len(labels)))
    for r in results:
        lf = r.get("lookforward", {})
        if not lf:
            continue
        cells = "".join(f"  {lf[l]['base_pct']:>+5.1f}%    " for l in labels if l in lf)
        print(f"  {r['ticker']:<8}  {r['price']:>8.2f}  {cells}")
    print()


def print_detail(r, cfg):
    print()
    print(f"  {'=' * 55}")
    print(f"  DETAILED ANALYSIS: {r['ticker']}")
    print(f"  {'=' * 55}")
    print(f"  Price:          ${r['price']}")
    print(f"  Signal:         {r['signal']}  (Legacy: {r['score']}/100)")
    print(f"  AI SwingScore:  {r['swing_score']}/100  |  Setup: {r['setup_type']}")
    print(f"  Win Rate:       {r['win_rate']}%  |  ATR: ${r['atr']:.4f}")
    print(f"  2-Month Change: {r['change_2m']:+.1f}%")
    print()
    print(f"  --- Indicators (EMA 20/50 + RSI + MACD + ATR) ---")
    print(f"  EMA 20:         ${r['ema_fast']}")
    print(f"  EMA 50:         ${r['ema_slow']}")
    print(f"  RSI (14):       {r['rsi']}")
    print(f"  MACD:           {r['macd']}")
    print(f"  Volume Ratio:   {r['volume_ratio']}x avg")
    print()
    print(f"  --- Trade Plan (ATR-Based) ---")
    print(f"  Entry:          ${r['entry']}")
    print(f"  Stop Loss:      ${r['stop_loss']}  (Entry − ATR×1.5)")
    print(f"  Target:         ${r['target']}  (Entry + 2×Risk)")
    print(f"  Risk/Reward:    1:{r['rr_ratio']}")
    print(f"  Risk Amount:    £{r['risk_amount']}  (3% of £{cfg['account_size']})")
    print(f"  Shares:         {r['shares']}  (£{r['position_value']})")
    print()
    print(f"  --- SwingScore Components ---")
    for k, v in r.get("score_components", {}).items():
        print(f"    {k:<25}: {v:.4f}")
    print()
    print(f"  --- Reasons ---")
    for reason in r["reasons"]:
        print(f"    * {reason}")

    lf = r.get("lookforward", {})
    if lf:
        print()
        print(f"  --- LookForward Projections ---")
        print(f"  {'Horizon':<8}  {'Base':>10}  {'Base%':>7}  {'Bull':>10}  {'Bear':>10}")
        print("  " + "-" * 52)
        for label, h in lf.items():
            print(f"  {label:<8}  ${h['base']:>9.2f}  {h['base_pct']:>+6.1f}%  "
                  f"${h['bull']:>9.2f}  ${h['bear']:>9.2f}")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI Swing Trading Agent")
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--top", type=int)
    parser.add_argument("--detail", type=str)
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--export", type=str)
    args = parser.parse_args()

    cfg = load_config()
    print_header()

    tickers = ([args.detail.upper()] if args.detail
               else [t.upper() for t in args.tickers] if args.tickers
               else cfg["watchlist"])

    min_score = args.min_score if args.min_score is not None else cfg.get("min_score", 30)

    print(f"\n  Scanning {len(tickers)} stocks...\n")
    results = []
    for i, ticker in enumerate(tickers):
        pct = int((i + 1) / len(tickers) * 100)
        print(f"\r  [{pct:>3}%] Analysing {ticker}...", end="", flush=True)
        result = analyze_stock(ticker, cfg)
        if result and result["swing_score"] >= min_score:
            results.append(result)

    print(f"\r  [100%] Done! {len(results)} stocks passed filter (>= {min_score})    ")

    if not results:
        print("\n  No stocks matched. Try lowering --min-score.")
        return

    if args.detail:
        print_detail(results[0], cfg)
    else:
        results = sorted(results, key=lambda x: x["swing_score"], reverse=True)
        print_summary_table(results, args.top)
        display = results[: args.top] if args.top else results
        print_lookforward_table(display)

    if args.export and results:
        import pandas as pd
        df = pd.DataFrame(results)
        df = df.drop(columns=["reasons", "lookforward", "score_components"], errors="ignore")
        df.to_csv(args.export, index=False)
        print(f"  Exported to {args.export}")

    top_buys = sorted(
        [r for r in results if "BUY" in r["signal"]],
        key=lambda x: x["swing_score"], reverse=True
    )[:3]
    if top_buys and not args.detail:
        print("\n  TOP AI PICKS:")
        for r in top_buys:
            print(f"    >> {r['ticker']} @ ${r['price']}  |  AI Score: {r['swing_score']}  |  "
                  f"Setup: {r['setup_type']}  |  Target: ${r['target']}  |  Stop: ${r['stop_loss']}")
        print()


if __name__ == "__main__":
    main()
