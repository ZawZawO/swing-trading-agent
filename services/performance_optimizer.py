"""
Performance Optimizer Service
==============================
Cache management, rate-limit tracking, and batch request utilities.
"""
import time
import threading
import logging
from collections import deque

logger = logging.getLogger("performance_optimizer")

# ─── Rate Limit Tracker ───────────────────────────────────────────────────────

class RateLimitTracker:
    """
    Tracks API call counts per source.
    Automatically pauses if threshold is exceeded within a window.
    """
    def __init__(self, max_calls: int = 5, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: deque = deque()
        self._lock = threading.Lock()

    def check_and_record(self) -> bool:
        """Returns True if the call is allowed, False if rate-limited."""
        now = time.time()
        with self._lock:
            # Remove old calls outside the window
            while self._calls and self._calls[0] < now - self.window:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True

    def wait_if_needed(self):
        """Block until a call slot is available."""
        while not self.check_and_record():
            logger.warning("[RATE_LIMIT] Throttling – sleeping 5s")
            time.sleep(5)


# Default rate limiters per source
polygon_limiter = RateLimitTracker(max_calls=5, window_seconds=60)
alpha_vantage_limiter = RateLimitTracker(max_calls=5, window_seconds=60)
yahoo_limiter = RateLimitTracker(max_calls=100, window_seconds=60)


# ─── Cache Stats ─────────────────────────────────────────────────────────────

def get_cache_stats() -> dict:
    """Return current cache state from data_fetcher."""
    try:
        from services.data_fetcher import _cache, CACHE_TTL
        now = time.time()
        total = len(_cache)
        fresh = sum(1 for v in _cache.values() if (now - v["ts"]) < CACHE_TTL)
        return {"total_entries": total, "fresh": fresh, "stale": total - fresh, "ttl_seconds": CACHE_TTL}
    except Exception:
        return {}


# ─── Batch Processor ─────────────────────────────────────────────────────────

def batch_fetch(
    tickers: list[str],
    fetch_fn,
    max_workers: int = 5,
) -> dict:
    """
    Execute fetch_fn(ticker) concurrently using a thread pool.
    Returns {ticker: result} dict.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_fn, ticker): ticker for ticker in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                results[ticker] = fut.result()
            except Exception as e:
                logger.warning(f"[BATCH] {ticker}: {e}")
                results[ticker] = None
    return results
