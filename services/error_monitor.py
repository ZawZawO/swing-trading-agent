"""
Error Monitor Service
=====================
Structured logging for API failures, setup detections, trade simulations,
and score calculations. Logs to /logs/ directory with rotation.
"""
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# ─── Configure rotating file loggers ─────────────────────────────────────────

def _make_logger(name: str, filename: str) -> logging.Logger:
    lg = logging.getLogger(name)
    if not lg.handlers:
        lg.setLevel(logging.DEBUG)
        fh = logging.handlers.RotatingFileHandler(
            _LOG_DIR / filename, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        lg.addHandler(fh)
        # Also propagate to root (console)
        lg.propagate = True
    return lg


_api_logger = _make_logger("api_errors", "api_errors.log")
_setup_logger = _make_logger("setup_detections", "setups.log")
_trade_logger = _make_logger("trade_simulations", "trades.log")
_score_logger = _make_logger("score_calculations", "scores.log")
_system_logger = _make_logger("system", "system.log")


# ─── Public helpers ───────────────────────────────────────────────────────────

def log_api_error(source: str, ticker: str, message: str):
    _api_logger.error(f"[{source.upper()}] {ticker}: {message}")


def log_setup(ticker: str, setup_type: str, price: float, score: float):
    _setup_logger.info(f"{ticker} | {setup_type} | price={price:.2f} | score={score:.1f}")


def log_trade(action: str, ticker: str, price: float, shares: int, pnl: float = None):
    if pnl is not None:
        _trade_logger.info(f"{action} | {ticker} | price={price:.2f} | shares={shares} | pnl={pnl:.2f}")
    else:
        _trade_logger.info(f"{action} | {ticker} | price={price:.2f} | shares={shares}")


def log_score(ticker: str, swing_score: float, components: dict):
    parts = " | ".join(f"{k}={v:.3f}" for k, v in components.items())
    _score_logger.info(f"{ticker} | swing_score={swing_score:.1f} | {parts}")


def log_system(level: str, message: str):
    fn = getattr(_system_logger, level.lower(), _system_logger.info)
    fn(message)


def get_recent_errors(n: int = 50) -> list[dict]:
    """Return last n lines from api_errors.log as dicts."""
    log_file = _LOG_DIR / "api_errors.log"
    if not log_file.exists():
        return []
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    result = []
    for line in lines[-n:]:
        parts = line.split(" | ", 2)
        result.append({
            "timestamp": parts[0] if len(parts) > 0 else "",
            "level": parts[1] if len(parts) > 1 else "",
            "message": parts[2] if len(parts) > 2 else line,
        })
    return list(reversed(result))
