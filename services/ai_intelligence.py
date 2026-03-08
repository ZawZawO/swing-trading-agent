"""
AI Intelligence Service
========================
5-Step Pipeline:
  Step 1 — Technical Analysis   (weight 40%)
  Step 2 — News Sentiment        (weight 20%)
  Step 3 — Social Sentiment      (weight 20%)
  Step 4 — Global Risk Score     (weight 20%)
  Step 5 — Final AI Score + Ranking

Endpoints served:
  /api/ai-weekly        → Top 3 trades (weekly universe, 6-hour cache)
  /api/market-scanner   → Top 10 trades (large universe, 24-hour cache + background)
  /api/professor-mode   → AI market advice
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

# ── VADER (optional but preferred) ────────────────────────────────────────────
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False

# ── Cache paths ────────────────────────────────────────────────────────────────
_CACHE_DIR  = Path(__file__).parent.parent
SCANNER_CACHE_FILE = _CACHE_DIR / "scanner_cache.json"

# ── Stock Universes ────────────────────────────────────────────────────────────

# ~160 curated liquid stocks across all major sectors
LARGE_UNIVERSE = [
    # ─ Mega-cap Tech ──────────────────────────────────────────────────────────
    "AAPL","MSFT","NVDA","META","GOOGL","AMZN","TSLA","AVGO","ORCL","CRM",
    "ADBE","CSCO","INTC","QCOM","TXN","AMD","MU","AMAT","LRCX","KLAC",
    # ─ Growth Tech ────────────────────────────────────────────────────────────
    "NFLX","NOW","PANW","CRWD","SNOW","PLTR","NET","ZS","DDOG","FTNT",
    "ARM","SMCI","MRVL","ON","MCHP","HUBS","TEAM","VEEV","OKTA","TWLO",
    # ─ Semiconductors ─────────────────────────────────────────────────────────
    "SWKS","MPWR","WOLF","OLED","ENTG","FORM","ACLS",
    # ─ Financials ─────────────────────────────────────────────────────────────
    "JPM","BAC","WFC","GS","MS","C","AXP","BLK","SCHW","V","MA",
    "PYPL","SQ","COIN","HOOD","SOFI","NU","AFRM","MARA","RIOT",
    # ─ Healthcare / Biotech ───────────────────────────────────────────────────
    "UNH","LLY","ABBV","MRK","AMGN","GILD","BIIB","REGN","VRTX","MRNA",
    "PFE","BMY","ISRG","DXCM","ALGN","IDXX","HCA","CVS","CI",
    # ─ Consumer ───────────────────────────────────────────────────────────────
    "WMT","COST","TGT","HD","LOW","NKE","SBUX","MCD","LULU","ROST","TJX",
    "ETSY","SHOP","DASH","LYFT","BABA","PDD",
    # ─ Energy ─────────────────────────────────────────────────────────────────
    "XOM","CVX","COP","SLB","EOG","OXY","DVN","MPC","VLO","PSX","HAL","AR",
    # ─ Industrial / Aerospace ─────────────────────────────────────────────────
    "BA","LMT","RTX","NOC","GD","CAT","DE","EMR","HON","GE","MMM",
    "UPS","FDX","DAL","UAL","AAL","LUV",
    # ─ Communication ──────────────────────────────────────────────────────────
    "DIS","CMCSA","T","VZ","TMUS","WBD","PARA",
    # ─ REITs ──────────────────────────────────────────────────────────────────
    "AMT","PLD","EQIX","CCI","SPG","O",
    # ─ Market ETFs (reference) ────────────────────────────────────────────────
    "SPY","QQQ","IWM","XLK","XLF","XLE","XLV","XLC","XLI",
]
LARGE_UNIVERSE = list(dict.fromkeys(LARGE_UNIVERSE))   # deduplicate

# Focused 80-stock universe for the weekly deep-analysis run
WEEKLY_UNIVERSE = [
    "AAPL","MSFT","NVDA","META","GOOGL","AMZN","TSLA","AVGO","CRM","ADBE",
    "AMD","NFLX","PLTR","COIN","MARA","SHOP","ARM","SMCI","CRWD","PANW",
    "NET","SNOW","ZS","DDOG","OKTA","NOW","HUBS","TEAM",
    "JPM","GS","V","MA","BAC","SCHW","PYPL","SQ","SOFI","NU","AFRM",
    "LLY","AMGN","MRNA","GILD","VRTX","UNH","ABBV","ISRG","BIIB","REGN",
    "XOM","CVX","OXY","COP","SLB","EOG",
    "BA","CAT","GE","DE","LMT","RTX","HON",
    "WMT","COST","NKE","LULU","SBUX","MCD","HD","TGT",
    "DIS","CMCSA","TMUS",
    "SPY","QQQ","IWM",
]
WEEKLY_UNIVERSE = list(dict.fromkeys(WEEKLY_UNIVERSE))


# ─────────────────────────────────────────────────────────────────────────────
# In-memory state
# ─────────────────────────────────────────────────────────────────────────────
_scanner_lock = threading.Lock()
_scanner_state = {"status": "idle", "last_run": 0, "results": []}

_weekly_cache  = {"results": [], "timestamp": 0, "ttl": 6 * 3600}
_risk_cache    = {"score": 50.0, "timestamp": 0, "ttl": 3600}


# ─────────────────────────────────────────────────────────────────────────────
# Disk cache helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_disk_cache():
    """Return cached scanner results if they are < 24 hours old."""
    if SCANNER_CACHE_FILE.exists():
        try:
            data = json.loads(SCANNER_CACHE_FILE.read_text())
            if time.time() - data.get("timestamp", 0) < 24 * 3600:
                return data.get("results", []), data.get("timestamp", time.time())
        except Exception:
            pass
    return None, None


def _save_disk_cache(results):
    try:
        SCANNER_CACHE_FILE.write_text(
            json.dumps({"timestamp": time.time(), "results": results})
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Technical Analysis
# ─────────────────────────────────────────────────────────────────────────────
def _technical_score(df: pd.DataFrame) -> dict | None:
    """
    Computes technical_score 0-100 plus trade levels.
    Input: daily OHLCV DataFrame (≥ 30 bars).
    """
    if df is None or df.empty or len(df) < 30:
        return None
    try:
        close  = df["Close"].astype(float)
        high   = df["High"].astype(float)
        low    = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        # EMAs
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - (100 / (1 + rs))

        # MACD 12/26/9
        ema12    = close.ewm(span=12, adjust=False).mean()
        ema26    = close.ewm(span=26, adjust=False).mean()
        macd     = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        macd_h   = macd - macd_sig

        # ATR-14
        tr = pd.concat(
            [high - low,
             (high - close.shift()).abs(),
             (low  - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean()

        # Volume ratio
        avg_vol   = volume.rolling(20).mean()
        vol_ratio = (float(volume.iloc[-1]) / float(avg_vol.iloc[-1])
                     if pd.notna(avg_vol.iloc[-1]) and float(avg_vol.iloc[-1]) > 0 else 1.0)

        price    = float(close.iloc[-1])
        e20      = float(ema20.iloc[-1])
        e50      = float(ema50.iloc[-1])
        e20_p    = float(ema20.iloc[-2]) if len(ema20) > 1 else e20
        e50_p    = float(ema50.iloc[-2]) if len(ema50) > 1 else e50
        rsi_v    = float(rsi.iloc[-1])   if pd.notna(rsi.iloc[-1])   else 50.0
        macd_v   = float(macd.iloc[-1])  if pd.notna(macd.iloc[-1])  else 0.0
        msig_v   = float(macd_sig.iloc[-1]) if pd.notna(macd_sig.iloc[-1]) else 0.0
        macd_pv  = float(macd.iloc[-2])  if pd.notna(macd.iloc[-2])  else 0.0
        msig_pv  = float(macd_sig.iloc[-2]) if pd.notna(macd_sig.iloc[-2]) else 0.0
        atr_v    = float(atr.iloc[-1])   if pd.notna(atr.iloc[-1])   else price * 0.02

        score = 50

        # ── EMA trend ──────────────────────────────────────────────────────
        if   e20 > e50 and e20_p <= e50_p: score += 22
        elif e20 > e50:                     score += 12
        elif e20 < e50 and e20_p >= e50_p: score -= 22
        elif e20 < e50:                     score -= 12

        # ── RSI ────────────────────────────────────────────────────────────
        if   rsi_v < 30: score += 18
        elif rsi_v < 40: score += 10
        elif rsi_v < 50: score +=  4
        elif rsi_v > 75: score -= 18
        elif rsi_v > 65: score -=  8

        # ── MACD ───────────────────────────────────────────────────────────
        if   macd_v > msig_v and macd_pv <= msig_pv: score += 16
        elif macd_v > msig_v and float(macd_h.iloc[-1]) > 0: score += 8
        elif macd_v < msig_v and macd_pv >= msig_pv: score -= 16
        elif macd_v < msig_v:                         score -=  8

        # ── Volume confirmation ────────────────────────────────────────────
        if   vol_ratio >= 2.0:  score += 12 if score > 50 else -6
        elif vol_ratio >= 1.5:  score +=  8 if score > 50 else -3

        score = max(0, min(100, score))

        # ── Setup detection ────────────────────────────────────────────────
        setup_type = "Neutral"
        if e20 > e50:
            if rsi_v < 45 and macd_v > msig_v:
                setup_type = "Pullback"
            elif macd_v > msig_v and vol_ratio >= 1.5:
                setup_type = "Breakout"
            elif abs(macd_v - msig_v) < 0.5 * abs(atr_v) and vol_ratio > 1.3:
                setup_type = "Range Break"
            else:
                setup_type = "Pullback" if rsi_v < 55 else "Breakout"

        # ── Trade levels (ATR-based) ───────────────────────────────────────
        entry      = round(price, 2)
        stop       = round(max(price - atr_v * 1.5, price * 0.95), 2)
        target     = round(price + (price - stop) * 2.0, 2)
        target_pct = round((target - entry) / entry * 100, 1)

        # ── Win-rate estimate (simple historical model) ────────────────────
        above50_count = int((close > close.rolling(50).mean()).sum())
        win_rate = round(above50_count / max(len(close), 1) * 100, 0)

        return {
            "technical_score": round(float(score), 1),
            "setup_type":       setup_type,
            "price":            entry,
            "entry":            entry,
            "stop_loss":        stop,
            "target":           target,
            "target_pct":       target_pct,
            "rsi":              round(rsi_v, 1),
            "ema20":            round(e20, 2),
            "ema50":            round(e50, 2),
            "volume_ratio":     round(vol_ratio, 2),
            "atr":              round(atr_v, 2),
            "win_rate":         win_rate,
        }
    except Exception as e:
        logger.debug(f"technical_score error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — News Sentiment
# ─────────────────────────────────────────────────────────────────────────────
_BULL_WORDS = {"buy","bullish","surge","rally","beat","record","growth",
               "strong","upgrade","outperform","soar","highs","breakout"}
_BEAR_WORDS = {"sell","bearish","crash","fall","miss","loss","weak",
               "downgrade","underperform","decline","warning","recession"}


def _news_sentiment_score(ticker: str) -> float:
    """Fetch latest headlines via yfinance and score them 0-100 (50 = neutral)."""
    try:
        news = yf.Ticker(ticker).news or []
        if not news:
            return 50.0
        scores = []
        for item in news[:10]:
            # yfinance ≥0.2 nests content
            title = (item.get("title") or
                     (item.get("content") or {}).get("title") or "")
            if not title:
                continue
            if VADER_AVAILABLE:
                compound = _vader.polarity_scores(title)["compound"]   # -1 … +1
                scores.append(compound)
            else:
                t = title.lower()
                b = sum(1 for w in _BULL_WORDS if w in t)
                k = sum(1 for w in _BEAR_WORDS if w in t)
                scores.append((b - k) * 0.25)

        if not scores:
            return 50.0
        avg = sum(scores) / len(scores)
        return round(min(100.0, max(0.0, (avg + 1.0) * 50.0)), 1)
    except Exception:
        return 50.0


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Social Sentiment
# ─────────────────────────────────────────────────────────────────────────────
def _social_sentiment_score(ticker: str, tech_data: dict) -> float:
    """
    Primary: Stocktwits public API (free, no key required).
    Fallback: momentum proxy derived from technical data.
    Returns 0-100.
    """
    # ── Stocktwits ─────────────────────────────────────────────────────────
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = requests.get(url, timeout=4,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            messages = resp.json().get("messages", [])[:30]
            bull = sum(1 for m in messages
                       if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish")
            bear = sum(1 for m in messages
                       if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish")
            total = bull + bear
            if total >= 3:
                return round(min(100.0, max(0.0, bull / total * 100.0)), 1)
    except Exception:
        pass

    # ── Momentum proxy ─────────────────────────────────────────────────────
    if not tech_data:
        return 50.0
    ts  = tech_data.get("technical_score", 50.0)
    vr  = tech_data.get("volume_ratio", 1.0)
    rv  = tech_data.get("rsi", 50.0)
    val = ts * 0.50 + min(vr / 3.0, 1.0) * 30.0 + (rv / 100.0) * 20.0
    return round(min(100.0, max(0.0, val)), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Global Risk Score
# ─────────────────────────────────────────────────────────────────────────────
def _global_risk_score() -> float:
    """
    Uses VIX + SPY trend → market health score 0-100 (higher = safer).
    Cached 1 hour.
    """
    now = time.time()
    if now - _risk_cache["timestamp"] < _risk_cache["ttl"]:
        return _risk_cache["score"]
    try:
        vix_df = yf.Ticker("^VIX").history(period="5d", interval="1d")
        vix    = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else 20.0

        spy_df = yf.Ticker("SPY").history(period="30d", interval="1d")
        spy_bullish = False
        if not spy_df.empty:
            c    = spy_df["Close"].astype(float)
            ema20 = c.ewm(span=20, adjust=False).mean()
            spy_bullish = float(c.iloc[-1]) > float(ema20.iloc[-1])

        # VIX → base score (lower VIX = safer market)
        if   vix < 13: base = 92
        elif vix < 17: base = 80
        elif vix < 20: base = 67
        elif vix < 25: base = 52
        elif vix < 30: base = 37
        elif vix < 35: base = 22
        else:           base = 10

        score = base + (8 if spy_bullish else -8)
        score = round(min(100.0, max(0.0, float(score))), 1)
        _risk_cache.update({"score": score, "timestamp": now})
        return score
    except Exception:
        return 50.0


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Final Score + Confidence
# ─────────────────────────────────────────────────────────────────────────────
def _final_score(tech: float, news: float, social: float, risk: float) -> float:
    return round(tech * 0.40 + news * 0.20 + social * 0.20 + risk * 0.20, 1)


def _confidence(score: float) -> str:
    if score >= 78: return "High"
    if score >= 62: return "Medium"
    return "Low"


# ─────────────────────────────────────────────────────────────────────────────
# Single ticker — full AI pipeline
# ─────────────────────────────────────────────────────────────────────────────
def _analyze_ticker(ticker: str, df: pd.DataFrame | None = None,
                    risk_score: float | None = None) -> dict | None:
    """Run all 5 steps for one ticker. df is daily OHLCV if pre-fetched."""
    try:
        if df is None or df.empty:
            df = yf.Ticker(ticker).history(period="3mo", interval="1d")
        if df is None or df.empty or len(df) < 30:
            return None

        tech = _technical_score(df)
        if not tech:
            return None

        news   = _news_sentiment_score(ticker)
        social = _social_sentiment_score(ticker, tech)
        risk   = risk_score if risk_score is not None else _global_risk_score()
        final  = _final_score(tech["technical_score"], news, social, risk)

        return {
            "ticker":           ticker,
            "swing_score":      final,
            "technical_score":  tech["technical_score"],
            "news_sentiment":   news,
            "social_sentiment": social,
            "market_risk_score": risk,
            "confidence":       _confidence(final),
            "setup_type":       tech["setup_type"],
            "price":            tech["price"],
            "entry":            tech["entry"],
            "stop_loss":        tech["stop_loss"],
            "target":           tech["target"],
            "target_pct":       tech["target_pct"],
            "rsi":              tech["rsi"],
            "volume_ratio":     tech["volume_ratio"],
            "win_rate":         tech["win_rate"],
        }
    except Exception as e:
        logger.debug(f"_analyze_ticker {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Bulk download helper
# ─────────────────────────────────────────────────────────────────────────────
def _bulk_download(universe: list) -> dict:
    """
    Downloads 3-month daily data for all tickers in one yfinance call.
    Returns {ticker: DataFrame}.
    """
    dfs = {}
    try:
        raw = yf.download(
            " ".join(universe),
            period="3mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        # MultiIndex structure: raw[ticker] → DataFrame with OHLCV columns
        for ticker in universe:
            try:
                if ticker in raw.columns.get_level_values(0):
                    df = raw[ticker].dropna()
                    if not df.empty and len(df) >= 30:
                        dfs[ticker] = df
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"bulk_download error: {e}")
    return dfs


# ─────────────────────────────────────────────────────────────────────────────
# Background large-universe scanner
# ─────────────────────────────────────────────────────────────────────────────
def _run_scanner_bg():
    """Runs in a daemon thread; populates _scanner_state."""
    global _scanner_state
    with _scanner_lock:
        _scanner_state["status"] = "running"

    try:
        logger.info(f"AI Scanner: downloading {len(LARGE_UNIVERSE)} tickers")
        dfs        = _bulk_download(LARGE_UNIVERSE)
        risk_score = _global_risk_score()
        results    = []

        for ticker in LARGE_UNIVERSE:
            df     = dfs.get(ticker)
            result = _analyze_ticker(ticker, df, risk_score=risk_score)
            if result:
                results.append(result)

        results.sort(key=lambda x: x["swing_score"], reverse=True)
        _save_disk_cache(results)
        logger.info(f"AI Scanner: complete — {len(results)} stocks analysed")

        with _scanner_lock:
            _scanner_state.update({
                "status":   "ready",
                "last_run": time.time(),
                "results":  results,
            })
    except Exception as e:
        logger.error(f"AI Scanner background error: {e}")
        with _scanner_lock:
            _scanner_state["status"] = "idle"


# ─────────────────────────────────────────────────────────────────────────────
# Public API: Large scanner
# ─────────────────────────────────────────────────────────────────────────────
def get_market_scanner(force_refresh: bool = False) -> dict:
    """
    Returns Top-10 results from the large universe scan.
    - Serves from 24-hour disk cache if available and not force_refresh.
    - Starts a background scan if no cache or force_refresh.
    - Returns status='running' while scan is in progress.
    """
    # Check disk cache first
    cached_results, cached_ts = _load_disk_cache()
    if cached_results and not force_refresh:
        with _scanner_lock:
            if _scanner_state["status"] != "running":
                _scanner_state.update({
                    "status":   "ready",
                    "last_run": cached_ts or time.time(),
                    "results":  cached_results,
                })
        last_scan = (datetime.fromtimestamp(cached_ts).strftime("%Y-%m-%d %H:%M")
                     if cached_ts else "N/A")
        return {
            "status":        "ready",
            "top10":         cached_results[:10],
            "total_scanned": len(cached_results),
            "last_scan":     last_scan,
            "cached":        True,
        }

    with _scanner_lock:
        status   = _scanner_state["status"]
        results  = _scanner_state["results"]
        last_run = _scanner_state["last_run"]

    if status == "ready" and not force_refresh:
        return {
            "status":        "ready",
            "top10":         results[:10],
            "total_scanned": len(results),
            "last_scan":     datetime.fromtimestamp(last_run).strftime("%Y-%m-%d %H:%M"),
            "cached":        True,
        }

    if status == "running":
        return {"status": "running", "top10": [], "total_scanned": 0,
                "last_scan": None, "cached": False}

    # Start background scan
    t = threading.Thread(target=_run_scanner_bg, daemon=True)
    t.start()
    return {"status": "started", "top10": [], "total_scanned": 0,
            "last_scan": None, "cached": False}


# ─────────────────────────────────────────────────────────────────────────────
# Public API: Weekly Top-3
# ─────────────────────────────────────────────────────────────────────────────
def get_weekly_top3(force_refresh: bool = False) -> dict:
    """
    Full 5-step pipeline on WEEKLY_UNIVERSE. Returns Top-3.
    Result cached for 6 hours in memory.
    """
    now = time.time()
    if (not force_refresh and
            _weekly_cache["results"] and
            now - _weekly_cache["timestamp"] < _weekly_cache["ttl"]):
        return {
            "top3":      _weekly_cache["results"][:3],
            "cached":    True,
            "last_scan": datetime.fromtimestamp(_weekly_cache["timestamp"]).strftime("%Y-%m-%d %H:%M"),
        }

    risk_score = _global_risk_score()
    results    = []

    # Batch download
    dfs = _bulk_download(WEEKLY_UNIVERSE)

    for ticker in WEEKLY_UNIVERSE:
        df     = dfs.get(ticker)
        result = _analyze_ticker(ticker, df, risk_score=risk_score)
        if result:
            results.append(result)

    results.sort(key=lambda x: x["swing_score"], reverse=True)
    _weekly_cache.update({"results": results, "timestamp": now})

    return {
        "top3":      results[:3],
        "cached":    False,
        "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API: Professor Mode
# ─────────────────────────────────────────────────────────────────────────────
def get_professor_mode() -> dict:
    """
    Analyses macro conditions and returns structured trading advice.
    """
    try:
        # ── VIX ────────────────────────────────────────────────────────────
        vix_df = yf.Ticker("^VIX").history(period="5d", interval="1d")
        vix    = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else 20.0

        # ── SPY trend ──────────────────────────────────────────────────────
        spy_df     = yf.Ticker("SPY").history(period="30d", interval="1d")
        spy_bullish = False
        spy_5d_ret  = 0.0
        if not spy_df.empty:
            c          = spy_df["Close"].astype(float)
            ema20      = c.ewm(span=20, adjust=False).mean()
            spy_bullish = float(c.iloc[-1]) > float(ema20.iloc[-1])
            if len(c) >= 5:
                spy_5d_ret = round((float(c.iloc[-1]) - float(c.iloc[-5])) /
                                   float(c.iloc[-5]) * 100, 2)

        # ── Sector ETF momentum (10-day return) ────────────────────────────
        sector_map = {
            "Technology":  "XLK",
            "Financials":  "XLF",
            "Energy":      "XLE",
            "Healthcare":  "XLV",
            "Consumer":    "XLC",
            "Industrials": "XLI",
        }
        sector_scores: dict[str, float] = {}
        for name, etf in sector_map.items():
            try:
                df = yf.Ticker(etf).history(period="10d", interval="1d")
                if not df.empty and len(df) >= 2:
                    c   = df["Close"].astype(float)
                    ret = (float(c.iloc[-1]) - float(c.iloc[0])) / float(c.iloc[0]) * 100
                    sector_scores[name] = round(ret, 2)
                else:
                    sector_scores[name] = 0.0
            except Exception:
                sector_scores[name] = 0.0

        best_sector  = max(sector_scores, key=sector_scores.get) if sector_scores else "Technology"
        worst_sector = min(sector_scores, key=sector_scores.get) if sector_scores else "Energy"

        # ── Market condition logic ──────────────────────────────────────────
        if vix < 15 and spy_bullish:
            market_condition = "Strongly Bullish"
            risk_level       = "Low"
            strategy         = ("Full risk-on mode. Trade breakout and pullback setups with "
                                 "full position sizes. Focus on leading sector: " + best_sector + ".")
        elif vix < 20 and spy_bullish:
            market_condition = "Moderately Bullish"
            risk_level       = "Low–Medium"
            strategy         = ("Favor pullback setups in confirmed uptrends. Keep stops tight "
                                 "at ATR × 1.5. Best sector strength: " + best_sector + ".")
        elif vix < 25:
            market_condition = "Neutral / Choppy"
            risk_level       = "Medium"
            strategy         = ("Be highly selective — only act on scores ≥ 72. "
                                 "Reduce position size by 25%. Range-Break setups preferred. "
                                 "Avoid " + worst_sector + ".")
        elif vix < 32:
            market_condition = "Cautious / Elevated Risk"
            risk_level       = "High"
            strategy         = ("Tighten stops. Take 50 % of target early. "
                                 "Avoid fresh entries in weak sectors. "
                                 "Consider inverse ETFs for hedging.")
        else:
            market_condition = "High Volatility / Crisis Mode"
            risk_level       = "Very High"
            strategy         = ("Capital preservation is priority. Reduce all positions. "
                                 "Stay 70 % cash. Only trade extreme oversold reversals "
                                 "with ≥ 2:1 reward-to-risk.")

        # ── Advice text ────────────────────────────────────────────────────
        vix_str  = f"VIX {vix:.1f}"
        spy_str  = f"SPY {'▲' if spy_bullish else '▼'} EMA20"
        best_ret = sector_scores.get(best_sector, 0.0)
        advice   = (
            f"Market is {market_condition.lower()}. {vix_str} · {spy_str} · "
            f"SPY 5-day: {spy_5d_ret:+.1f}%. "
            f"Strongest sector: {best_sector} ({best_ret:+.1f}%). "
            f"{strategy}"
        )

        return {
            "market_condition":    market_condition,
            "vix":                 round(vix, 2),
            "spy_bullish":         spy_bullish,
            "spy_5d_return":       spy_5d_ret,
            "risk_level":          risk_level,
            "recommended_strategy": strategy,
            "sector_strength":     sector_scores,
            "best_sector":         best_sector,
            "worst_sector":        worst_sector,
            "advice":              advice,
            "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    except Exception as e:
        logger.error(f"professor_mode error: {e}")
        return {
            "market_condition":    "Unknown",
            "vix":                 0,
            "spy_bullish":         False,
            "spy_5d_return":       0.0,
            "risk_level":          "Medium",
            "recommended_strategy": "Market intelligence temporarily unavailable.",
            "sector_strength":     {},
            "best_sector":         "N/A",
            "worst_sector":        "N/A",
            "advice":              "Unable to fetch market data. Please try again shortly.",
            "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
