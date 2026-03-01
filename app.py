"""
Swing Trading Dashboard - Web Server
=====================================
Flask app that serves a web dashboard for the swing trading agent.
Reuses all analysis functions from swing_agent.py.

Usage:
    python app.py
    Then open http://localhost:5000
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, render_template, request

from swing_agent import (
    analyze_stock,
    calc_ema,
    calc_macd,
    calc_rsi,
    find_support_resistance,
    load_config,
)

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent / "config.json"
JOURNAL_PATH = Path(__file__).parent / "journal.json"


# ─── Chart Data Helper ───────────────────────────────────────────────────────

def get_chart_data(ticker, cfg):
    """Fetch OHLCV + indicator time-series for charting."""
    end = datetime.now()
    start = end - timedelta(days=cfg["lookback_days"])

    stock = yf.Ticker(ticker)
    df = stock.history(start=start, end=end, interval=cfg["interval"])

    if df.empty or len(df) < 50:
        return None

    close = df["Close"]

    ema_fast = calc_ema(close, cfg["ema_fast"])
    ema_slow = calc_ema(close, cfg["ema_slow"])
    rsi = calc_rsi(close, cfg["rsi_period"])
    macd_line, signal_line, macd_hist = calc_macd(
        close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
    )

    def to_ts(idx):
        return int(idx.timestamp())

    candles = []
    for i in range(len(df)):
        candles.append({
            "time": to_ts(df.index[i]),
            "open": round(float(df["Open"].iloc[i]), 2),
            "high": round(float(df["High"].iloc[i]), 2),
            "low": round(float(df["Low"].iloc[i]), 2),
            "close": round(float(df["Close"].iloc[i]), 2),
        })

    volumes = []
    for i in range(len(df)):
        color = "rgba(38,166,154,0.5)" if df["Close"].iloc[i] >= df["Open"].iloc[i] else "rgba(239,83,80,0.5)"
        volumes.append({
            "time": to_ts(df.index[i]),
            "value": int(df["Volume"].iloc[i]),
            "color": color,
        })

    def series_to_list(series):
        result = []
        for i in range(len(series)):
            val = series.iloc[i]
            if pd.notna(val):
                result.append({"time": to_ts(df.index[i]), "value": round(float(val), 4)})
        return result

    return {
        "candles": candles,
        "volumes": volumes,
        "ema_fast": series_to_list(ema_fast),
        "ema_slow": series_to_list(ema_slow),
        "rsi": series_to_list(rsi),
        "macd": series_to_list(macd_line),
        "macd_signal": series_to_list(signal_line),
        "macd_hist": series_to_list(macd_hist),
    }


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan")
def api_scan():
    cfg = load_config()
    results = []
    for ticker in cfg["watchlist"]:
        result = analyze_stock(ticker, cfg)
        if result:
            results.append(result)
    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({
        "results": results,
        "config": cfg,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/stock/<ticker>")
def api_stock(ticker):
    cfg = load_config()
    ticker = ticker.upper()
    analysis = analyze_stock(ticker, cfg)
    chart = get_chart_data(ticker, cfg)
    if not analysis:
        return jsonify({"error": f"Could not analyze {ticker}"}), 404
    return jsonify({
        "analysis": analysis,
        "chart": chart,
    })


@app.route("/api/config")
def api_get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def api_set_config():
    new_cfg = request.get_json()
    with open(CONFIG_PATH, "w") as f:
        json.dump(new_cfg, f, indent=4)
    return jsonify(load_config())


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist():
    data = request.get_json()
    action = data.get("action")
    ticker = data.get("ticker", "").upper()
    cfg = load_config()
    if action == "add" and ticker and ticker not in cfg["watchlist"]:
        cfg["watchlist"].append(ticker)
    elif action == "remove" and ticker in cfg["watchlist"]:
        cfg["watchlist"].remove(ticker)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)
    return jsonify({"watchlist": cfg["watchlist"]})


# ─── Feature 4: Live Prices ─────────────────────────────────────────────────

@app.route("/api/prices")
def api_prices():
    cfg = load_config()
    prices = {}
    for ticker in cfg["watchlist"]:
        try:
            stock = yf.Ticker(ticker)
            prices[ticker] = {"price": round(float(stock.fast_info.last_price), 2)}
        except Exception:
            try:
                stock = yf.Ticker(ticker)
                h = stock.history(period="1d", interval="1m")
                if not h.empty:
                    prices[ticker] = {"price": round(float(h["Close"].iloc[-1]), 2)}
                else:
                    prices[ticker] = {"price": None}
            except Exception:
                prices[ticker] = {"price": None}
    return jsonify({"prices": prices, "timestamp": datetime.now().isoformat()})


# ─── Earnings Shield ────────────────────────────────────────────────────────

_earnings_cache = {"data": {}, "timestamp": 0, "ttl": 3600}


@app.route("/api/earnings")
def api_earnings():
    """Get next earnings dates for all watchlist stocks. Cached for 1 hour."""
    cfg = load_config()
    now = time.time()

    if now - _earnings_cache["timestamp"] < _earnings_cache["ttl"] and _earnings_cache["data"]:
        return jsonify({"earnings": _earnings_cache["data"], "cached": True})

    earnings = {}
    for ticker in cfg["watchlist"]:
        try:
            stock = yf.Ticker(ticker)
            dates = stock.earnings_dates
            if dates is not None and not dates.empty:
                future = dates[dates.index >= pd.Timestamp.now(tz=dates.index.tz)]
                if not future.empty:
                    next_date = future.index[0]
                    if next_date.tzinfo is not None:
                        next_date = next_date.tz_convert("US/Eastern").tz_localize(None)
                    days_until = (next_date - pd.Timestamp.now()).days
                    earnings[ticker] = {
                        "next_date": next_date.strftime("%Y-%m-%d"),
                        "days_until": days_until,
                        "eps_estimate": None,
                    }
                    if "EPS Estimate" in future.columns:
                        est = future.iloc[0]["EPS Estimate"]
                        if pd.notna(est):
                            earnings[ticker]["eps_estimate"] = round(float(est), 2)
                else:
                    earnings[ticker] = None
            else:
                earnings[ticker] = None
        except Exception:
            earnings[ticker] = None

    _earnings_cache["data"] = earnings
    _earnings_cache["timestamp"] = now
    return jsonify({"earnings": earnings, "cached": False})


# ─── Feature 3: Notes & Journal ─────────────────────────────────────────────

@app.route("/api/notes", methods=["POST"])
def api_save_note():
    data = request.get_json()
    ticker = data.get("ticker", "").upper()
    note = data.get("note", "")
    cfg = load_config()
    if "notes" not in cfg:
        cfg["notes"] = {}
    if note.strip():
        cfg["notes"][ticker] = note
    else:
        cfg["notes"].pop(ticker, None)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)
    return jsonify({"notes": cfg["notes"]})


@app.route("/api/journal")
def api_get_journal():
    if JOURNAL_PATH.exists():
        with open(JOURNAL_PATH) as f:
            journal = json.load(f)
    else:
        journal = []
    return jsonify({"entries": journal})


@app.route("/api/journal", methods=["POST"])
def api_save_journal():
    data = request.get_json()
    action = data.get("action")
    if JOURNAL_PATH.exists():
        with open(JOURNAL_PATH) as f:
            journal = json.load(f)
    else:
        journal = []
    if action == "add":
        entry = data.get("entry", {})
        entry["id"] = max([e.get("id", 0) for e in journal], default=0) + 1
        journal.append(entry)
    elif action == "delete":
        entry_id = data.get("id")
        journal = [e for e in journal if e.get("id") != entry_id]
    with open(JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=4)
    return jsonify({"entries": journal})


# ─── Feature 2: Backtest ────────────────────────────────────────────────────

@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data = request.get_json()
    ticker = data.get("ticker", "").upper()
    days = data.get("days", 180)
    cfg = load_config()

    end = datetime.now()
    start = end - timedelta(days=days)

    stock = yf.Ticker(ticker)
    df = stock.history(start=start, end=end, interval=cfg["interval"])

    if df.empty or len(df) < 50:
        return jsonify({"error": "Not enough data"}), 400

    close = df["Close"]
    volume = df["Volume"]

    ema_fast = calc_ema(close, cfg["ema_fast"])
    ema_slow = calc_ema(close, cfg["ema_slow"])
    rsi = calc_rsi(close, cfg["rsi_period"])
    macd_line, signal_line, macd_hist = calc_macd(
        close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
    )
    avg_volume = volume.rolling(window=20).mean()

    # Compute score at each bar
    scores = []
    for i in range(len(df)):
        if i < 1:
            scores.append(50)
            continue
        score = 50
        # EMA
        if ema_fast.iloc[i] > ema_slow.iloc[i] and ema_fast.iloc[i-1] <= ema_slow.iloc[i-1]:
            score += 20
        elif ema_fast.iloc[i] > ema_slow.iloc[i]:
            score += 10
        elif ema_fast.iloc[i] < ema_slow.iloc[i] and ema_fast.iloc[i-1] >= ema_slow.iloc[i-1]:
            score -= 20
        elif ema_fast.iloc[i] < ema_slow.iloc[i]:
            score -= 10
        # RSI
        rsi_val = rsi.iloc[i]
        if pd.notna(rsi_val):
            if rsi_val < 30: score += 15
            elif rsi_val < 40: score += 8
            elif rsi_val > 70: score -= 15
            elif rsi_val > 60: score -= 5
        # MACD
        if pd.notna(macd_line.iloc[i]) and pd.notna(signal_line.iloc[i]):
            if macd_line.iloc[i] > signal_line.iloc[i] and macd_line.iloc[i-1] <= signal_line.iloc[i-1]:
                score += 15
            elif macd_line.iloc[i] > signal_line.iloc[i] and macd_hist.iloc[i] > 0:
                score += 8
            elif macd_line.iloc[i] < signal_line.iloc[i] and macd_line.iloc[i-1] >= signal_line.iloc[i-1]:
                score -= 15
            elif macd_line.iloc[i] < signal_line.iloc[i]:
                score -= 8
        # Volume
        if pd.notna(avg_volume.iloc[i]) and avg_volume.iloc[i] > 0:
            vol_ratio = volume.iloc[i] / avg_volume.iloc[i]
            if vol_ratio >= cfg.get("volume_spike_multiplier", 1.5):
                if score > 50: score += 10
                else: score -= 5
        scores.append(max(0, min(100, score)))

    # Detect trades
    trades = []
    in_trade = False
    entry_price = entry_time = 0
    for i in range(len(scores)):
        if not in_trade and scores[i] >= 60:
            in_trade = True
            entry_price = float(close.iloc[i])
            entry_time = int(df.index[i].timestamp())
        elif in_trade and scores[i] < 60:
            in_trade = False
            exit_price = float(close.iloc[i])
            exit_time = int(df.index[i].timestamp())
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            trades.append({
                "entry_time": entry_time, "entry_price": round(entry_price, 2),
                "exit_time": exit_time, "exit_price": round(exit_price, 2),
                "return_pct": round(pnl_pct, 2),
            })
    if in_trade:
        exit_price = float(close.iloc[-1])
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        trades.append({
            "entry_time": entry_time, "entry_price": round(entry_price, 2),
            "exit_time": int(df.index[-1].timestamp()), "exit_price": round(exit_price, 2),
            "return_pct": round(pnl_pct, 2), "open": True,
        })

    # Summary
    total = len(trades)
    wins = [t for t in trades if t["return_pct"] > 0]
    win_rate = (len(wins) / total * 100) if total > 0 else 0
    avg_ret = (sum(t["return_pct"] for t in trades) / total) if total > 0 else 0
    total_ret = sum(t["return_pct"] for t in trades)
    equity = [0]
    for t in trades:
        equity.append(equity[-1] + t["return_pct"])
    peak = max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = peak - e
        if dd > max_dd: max_dd = dd

    def to_ts(idx):
        return int(idx.timestamp())

    candles = [{
        "time": to_ts(df.index[i]),
        "open": round(float(df["Open"].iloc[i]), 2),
        "high": round(float(df["High"].iloc[i]), 2),
        "low": round(float(df["Low"].iloc[i]), 2),
        "close": round(float(df["Close"].iloc[i]), 2),
    } for i in range(len(df))]

    markers = []
    for t in trades:
        markers.append({"time": t["entry_time"], "position": "belowBar", "color": "#26a69a", "shape": "arrowUp", "text": f"BUY ${t['entry_price']}"})
        markers.append({"time": t["exit_time"], "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": f"SELL ${t['exit_price']}"})
    markers.sort(key=lambda m: m["time"])

    return jsonify({
        "ticker": ticker, "days": days, "candles": candles, "markers": markers, "trades": trades,
        "summary": {
            "total_trades": total, "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2), "total_return": round(total_ret, 2),
            "max_drawdown": round(max_dd, 2), "wins": len(wins), "losses": total - len(wins),
        },
    })


# ─── Multi-Timeframe Analysis ──────────────────────────────────────────────


def resample_to_4h(df_1h):
    """Resample 1H OHLCV to 4H candles grouped by trading day."""
    df = df_1h.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_convert("US/Eastern")
    else:
        df.index = df.index.tz_localize("UTC").tz_convert("US/Eastern")
    df["_date"] = df.index.date
    df["_bucket"] = (df.index.hour - 9) // 4
    grouped = df.groupby(["_date", "_bucket"])
    df_4h = grouped.agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()
    first_ts = grouped.apply(lambda g: g.index[0])
    df_4h.index = first_ts.values
    df_4h.index.name = "Datetime"
    return df_4h


def analyze_from_dataframe(df, ticker, cfg):
    """Run scoring logic on a pre-existing DataFrame (for 4H resampled data)."""
    if df.empty or len(df) < 20:
        return None
    close = df["Close"]
    volume = df["Volume"]
    ema_fast = calc_ema(close, cfg["ema_fast"])
    ema_slow = calc_ema(close, cfg["ema_slow"])
    rsi = calc_rsi(close, cfg["rsi_period"])
    macd_line, signal_line, macd_hist = calc_macd(
        close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
    )
    avg_volume = volume.rolling(window=20).mean()

    price = round(float(close.iloc[-1]), 2)
    ema_f = round(float(ema_fast.iloc[-1]), 2)
    ema_s = round(float(ema_slow.iloc[-1]), 2)
    rsi_val = round(float(rsi.iloc[-1]), 2) if pd.notna(rsi.iloc[-1]) else 50
    macd_val = round(float(macd_line.iloc[-1]), 4) if pd.notna(macd_line.iloc[-1]) else 0
    macd_sig = round(float(signal_line.iloc[-1]), 4) if pd.notna(signal_line.iloc[-1]) else 0
    macd_h = round(float(macd_hist.iloc[-1]), 4) if pd.notna(macd_hist.iloc[-1]) else 0
    vol_avg = avg_volume.iloc[-1]
    vol_ratio = round(float(volume.iloc[-1] / vol_avg), 2) if pd.notna(vol_avg) and vol_avg > 0 else 0

    ema_f_prev = float(ema_fast.iloc[-2])
    ema_s_prev = float(ema_slow.iloc[-2])
    macd_prev = float(macd_line.iloc[-2]) if pd.notna(macd_line.iloc[-2]) else 0
    macd_sig_prev = float(signal_line.iloc[-2]) if pd.notna(signal_line.iloc[-2]) else 0

    score = 50
    reasons = []
    if ema_f > ema_s and ema_f_prev <= ema_s_prev:
        score += 20; reasons.append("EMA bullish crossover (fresh)")
    elif ema_f > ema_s:
        score += 10; reasons.append("EMA bullish trend")
    elif ema_f < ema_s and ema_f_prev >= ema_s_prev:
        score -= 20; reasons.append("EMA bearish crossover (fresh)")
    elif ema_f < ema_s:
        score -= 10; reasons.append("EMA bearish trend")

    if rsi_val < 30:
        score += 15; reasons.append(f"RSI oversold at {rsi_val}")
    elif rsi_val < 40:
        score += 8; reasons.append(f"RSI approaching oversold at {rsi_val}")
    elif rsi_val > 70:
        score -= 15; reasons.append(f"RSI overbought at {rsi_val}")
    elif rsi_val > 60:
        score -= 5; reasons.append(f"RSI elevated at {rsi_val}")

    if macd_val > macd_sig and macd_prev <= macd_sig_prev:
        score += 15; reasons.append("MACD bullish crossover")
    elif macd_val > macd_sig and macd_h > 0:
        score += 8; reasons.append("MACD bullish")
    elif macd_val < macd_sig and macd_prev >= macd_sig_prev:
        score -= 15; reasons.append("MACD bearish crossover")
    elif macd_val < macd_sig:
        score -= 8; reasons.append("MACD bearish")

    if vol_ratio >= cfg.get("volume_spike_multiplier", 1.5):
        if score > 50:
            score += 10; reasons.append(f"Volume spike {vol_ratio}x bullish")
        else:
            score -= 5; reasons.append(f"Volume spike {vol_ratio}x bearish")

    score = max(0, min(100, score))
    if score >= 70: signal = "STRONG BUY"
    elif score >= 60: signal = "BUY"
    elif score >= 40: signal = "HOLD"
    elif score >= 30: signal = "SELL"
    else: signal = "STRONG SELL"

    return {
        "ticker": ticker, "price": price, "signal": signal, "score": score,
        "ema_fast": ema_f, "ema_slow": ema_s, "rsi": rsi_val,
        "macd": macd_val, "macd_signal": macd_sig, "macd_hist": macd_h,
        "volume_ratio": vol_ratio, "reasons": reasons,
    }


def check_alignment(r1h, r4h, r1d):
    """Check if timeframes agree on direction."""
    def direction(r):
        if r is None: return None
        if r["score"] >= 60: return "bullish"
        elif r["score"] <= 40: return "bearish"
        return "neutral"
    dirs = [direction(r) for r in [r1h, r4h, r1d] if r is not None]
    if len(dirs) < 2: return None
    non_neutral = [d for d in dirs if d != "neutral"]
    if not non_neutral: return True
    return len(set(non_neutral)) == 1


@app.route("/api/mtf/<ticker>")
def api_mtf(ticker):
    """Multi-timeframe analysis: 1H, 4H (resampled), Daily."""
    cfg = load_config()
    ticker = ticker.upper()
    result_1h = analyze_stock(ticker, cfg)
    if not result_1h:
        return jsonify({"error": f"Could not analyze {ticker}"}), 404

    # 4H from resampled 1H data
    end = datetime.now()
    start = end - timedelta(days=cfg["lookback_days"])
    result_4h = None
    try:
        df_1h = yf.Ticker(ticker).history(start=start, end=end, interval="1h")
        if not df_1h.empty and len(df_1h) >= 50:
            df_4h = resample_to_4h(df_1h)
            if len(df_4h) >= 20:
                result_4h = analyze_from_dataframe(df_4h, ticker, cfg)
    except Exception:
        pass

    # Daily
    cfg_daily = {**cfg, "interval": "1d", "lookback_days": 120}
    result_daily = analyze_stock(ticker, cfg_daily)

    aligned = check_alignment(result_1h, result_4h, result_daily)
    return jsonify({
        "ticker": ticker,
        "timeframes": {"1h": result_1h, "4h": result_4h, "1d": result_daily},
        "aligned": aligned,
    })


@app.route("/api/mtf-alignment")
def api_mtf_alignment():
    """Quick alignment check for all watchlist stocks."""
    cfg = load_config()
    alignment = {}
    for ticker in cfg["watchlist"]:
        try:
            r1h = analyze_stock(ticker, cfg)
            if not r1h:
                alignment[ticker] = None
                continue
            end = datetime.now()
            start = end - timedelta(days=cfg["lookback_days"])
            r4h = None
            try:
                df_1h = yf.Ticker(ticker).history(start=start, end=end, interval="1h")
                if not df_1h.empty and len(df_1h) >= 50:
                    df_4h = resample_to_4h(df_1h)
                    if len(df_4h) >= 20:
                        r4h = analyze_from_dataframe(df_4h, ticker, cfg)
            except Exception:
                pass
            cfg_daily = {**cfg, "interval": "1d", "lookback_days": 120}
            r1d = analyze_stock(ticker, cfg_daily)
            alignment[ticker] = check_alignment(r1h, r4h, r1d)
        except Exception:
            alignment[ticker] = None
    return jsonify({"alignment": alignment})


# ─── Portfolio Tracker ─────────────────────────────────────────────────────


@app.route("/api/portfolio")
def api_portfolio():
    """Portfolio overview with live prices and P&L."""
    cfg = load_config()
    if JOURNAL_PATH.exists():
        with open(JOURNAL_PATH) as f:
            journal = json.load(f)
    else:
        journal = []

    open_positions = [e for e in journal if e.get("exit_price") is None]
    tickers_needed = list(set(e.get("ticker", "").upper() for e in open_positions))

    live_prices = {}
    for t in tickers_needed:
        try:
            live_prices[t] = round(float(yf.Ticker(t).fast_info.last_price), 2)
        except Exception:
            try:
                h = yf.Ticker(t).history(period="1d", interval="1m")
                live_prices[t] = round(float(h["Close"].iloc[-1]), 2) if not h.empty else None
            except Exception:
                live_prices[t] = None

    positions = []
    total_invested = total_current = total_unrealized = total_risk = 0
    for entry in open_positions:
        t = entry.get("ticker", "").upper()
        ep = entry.get("entry_price", 0)
        sh = entry.get("shares", 1)
        cp = live_prices.get(t)
        days_held = None
        if entry.get("entry_date"):
            try:
                days_held = (datetime.now() - datetime.strptime(entry["entry_date"], "%Y-%m-%d")).days
            except Exception:
                pass
        pos = {
            "id": entry.get("id"), "ticker": t, "type": entry.get("type", "BUY"),
            "entry_price": ep, "entry_date": entry.get("entry_date"),
            "shares": sh, "current_price": cp, "notes": entry.get("notes", ""),
            "days_held": days_held,
        }
        if cp is not None:
            invested = ep * sh
            cur_val = cp * sh
            pnl = cur_val - invested
            pnl_pct = ((cp - ep) / ep * 100) if ep > 0 else 0
            pos.update({"invested": round(invested, 2), "current_value": round(cur_val, 2),
                        "unrealized_pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)})
            total_invested += invested
            total_current += cur_val
            total_unrealized += pnl
            total_risk += invested * 0.02
        else:
            pos.update({"invested": round(ep * sh, 2), "current_value": None,
                        "unrealized_pnl": None, "pnl_pct": None})
        positions.append(pos)

    account_size = cfg.get("account_size", 10000)
    heat = round((total_risk / account_size * 100), 2) if account_size > 0 else 0

    closed = sorted(
        [e for e in journal if e.get("exit_price") is not None and e.get("exit_date")],
        key=lambda e: e.get("exit_date", "")
    )
    equity_curve = [{"date": "Start", "value": account_size}]
    running = account_size
    for trade in closed:
        pnl = (trade["exit_price"] - trade["entry_price"]) * trade.get("shares", 1)
        running += pnl
        equity_curve.append({"date": trade["exit_date"], "value": round(running, 2),
                             "ticker": trade["ticker"], "pnl": round(pnl, 2)})
    if total_unrealized != 0:
        equity_curve.append({"date": datetime.now().strftime("%Y-%m-%d"),
                             "value": round(running + total_unrealized, 2), "note": "unrealized"})

    summary = {
        "total_positions": len(positions),
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_unrealized_pct": round((total_unrealized / total_invested * 100), 2) if total_invested > 0 else 0,
        "portfolio_heat": heat,
        "account_size": account_size,
    }
    return jsonify({"positions": positions, "summary": summary, "equity_curve": equity_curve})


@app.route("/api/portfolio/close", methods=["POST"])
def api_close_position():
    """Close an open position."""
    data = request.get_json()
    entry_id = data.get("id")
    exit_price = data.get("exit_price")
    exit_date = data.get("exit_date", datetime.now().strftime("%Y-%m-%d"))
    if not JOURNAL_PATH.exists():
        return jsonify({"error": "No journal found"}), 404
    with open(JOURNAL_PATH) as f:
        journal = json.load(f)
    found = False
    for entry in journal:
        if entry.get("id") == entry_id:
            entry["exit_price"] = exit_price
            entry["exit_date"] = exit_date
            found = True
            break
    if not found:
        return jsonify({"error": "Position not found"}), 404
    with open(JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=4)
    return jsonify({"success": True})


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Swing Trading Dashboard")
    print(f"  Open http://localhost:{port} in your browser\n")
    app.run(debug=False, host="0.0.0.0", port=port)
