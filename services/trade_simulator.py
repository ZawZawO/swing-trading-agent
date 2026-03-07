"""
Trade Simulator Service
=======================
Simulates paper trades with £300 capital.
Tracks entry/exit, P&L, and performance metrics.
Persists to simulator_trades.json.
"""
import json
import time
import threading
from datetime import datetime
from pathlib import Path

import yfinance as yf

from services.error_monitor import log_trade

_TRADES_FILE = Path(__file__).parent.parent / "simulator_trades.json"
_lock = threading.Lock()

INITIAL_CAPITAL = 300.0


# ─── Persistence ─────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if _TRADES_FILE.exists():
        try:
            with open(_TRADES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(trades: list[dict]):
    with open(_TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2)


# ─── Live Price ───────────────────────────────────────────────────────────────

def _get_live_price(ticker: str) -> float | None:
    try:
        return round(float(yf.Ticker(ticker).fast_info.last_price), 4)
    except Exception:
        try:
            h = yf.Ticker(ticker).history(period="1d", interval="1m")
            return round(float(h["Close"].iloc[-1]), 4) if not h.empty else None
        except Exception:
            return None


# ─── Public API ───────────────────────────────────────────────────────────────

def open_trade(
    ticker: str,
    entry_price: float,
    shares: int,
    stop_loss: float,
    target: float,
    setup_type: str = "Manual",
    swing_score: float = 0.0,
) -> dict:
    """Open a new simulated trade."""
    with _lock:
        trades = _load()
        trade_id = max((t.get("id", 0) for t in trades), default=0) + 1
        trade = {
            "id": trade_id,
            "ticker": ticker.upper(),
            "entry_price": round(entry_price, 4),
            "shares": shares,
            "stop_loss": round(stop_loss, 4),
            "target": round(target, 4),
            "setup_type": setup_type,
            "swing_score": swing_score,
            "open_date": datetime.now().strftime("%Y-%m-%d"),
            "open_ts": int(time.time()),
            "status": "OPEN",
            "exit_price": None,
            "close_date": None,
        }
        trades.append(trade)
        _save(trades)
        log_trade("OPEN", ticker, entry_price, shares)
        return trade


def close_trade(trade_id: int, exit_price: float) -> dict | None:
    """Close an open simulated trade."""
    with _lock:
        trades = _load()
        for t in trades:
            if t.get("id") == trade_id and t.get("status") == "OPEN":
                t["exit_price"] = round(exit_price, 4)
                t["close_date"] = datetime.now().strftime("%Y-%m-%d")
                t["status"] = "CLOSED"
                pnl = (exit_price - t["entry_price"]) * t["shares"]
                t["pnl"] = round(pnl, 2)
                t["pnl_pct"] = round((exit_price - t["entry_price"]) / t["entry_price"] * 100, 2)
                _save(trades)
                log_trade("CLOSE", t["ticker"], exit_price, t["shares"], pnl)
                return t
        return None


def get_trades(status: str = None) -> list[dict]:
    """Return all trades, optionally filtered by status."""
    with _lock:
        trades = _load()
    if status:
        trades = [t for t in trades if t.get("status") == status.upper()]
    return trades


def get_trades_with_live_pnl() -> list[dict]:
    """Return open trades enriched with live P&L."""
    trades = get_trades(status="OPEN")
    enriched = []
    for t in trades:
        t = dict(t)
        live = _get_live_price(t["ticker"])
        if live is not None:
            t["current_price"] = live
            t["unrealized_pnl"] = round((live - t["entry_price"]) * t["shares"], 2)
            t["unrealized_pct"] = round((live - t["entry_price"]) / t["entry_price"] * 100, 2)
        else:
            t["current_price"] = None
            t["unrealized_pnl"] = None
            t["unrealized_pct"] = None
        enriched.append(t)
    return enriched


def get_summary() -> dict:
    """Compute performance summary across all closed trades."""
    with _lock:
        trades = _load()
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]
    open_t = [t for t in trades if t.get("status") == "OPEN"]

    total = len(closed)
    wins = sum(1 for t in closed if t["pnl"] > 0)
    losses = total - wins
    total_pnl = sum(t["pnl"] for t in closed)
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
    avg_pnl = round(total_pnl / total, 2) if total > 0 else 0.0

    return {
        "capital": INITIAL_CAPITAL,
        "total_trades": total,
        "open_trades": len(open_t),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": avg_pnl,
        "net_capital": round(INITIAL_CAPITAL + total_pnl, 2),
    }


def delete_trade(trade_id: int) -> bool:
    """Remove a trade from the simulator."""
    with _lock:
        trades = _load()
        before = len(trades)
        trades = [t for t in trades if t.get("id") != trade_id]
        if len(trades) < before:
            _save(trades)
            return True
        return False
