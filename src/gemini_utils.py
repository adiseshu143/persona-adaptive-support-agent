"""
gemini_utils.py
---------------
Shared Gemini client (singleton) + retry/backoff + quota cooldown tracking.

This is the SINGLE place that owns:
  • the genai.Client instance (created once, reused everywhere)
  • retry-with-backoff for transient errors (429 / RESOURCE_EXHAUSTED)
  • a short-lived "cooldown" flag so that once we know quota is exhausted,
    we stop burning further requests against it for a while and let
    callers fall back immediately instead of retrying into a wall.
"""
from src import config

print("CONFIG FILE:", config.__file__)
print("HAS RETRIES:", hasattr(config, "GEMINI_MAX_RETRIES"))
print("CONFIG ATTRS:", dir(config))
import time
import threading

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

from google import genai

from src import config

_lock = threading.Lock()
_client = None


def get_client():
    """Process-wide singleton Gemini client."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ── Quota cooldown ────────────────────────────────────────────────────────────
class _QuotaState:
    """Tracks the last time we hit a 429 so we can short-circuit further
    Gemini calls instead of immediately retrying into a still-exhausted quota."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_429_at = 0.0

    def mark_exhausted(self):
        with self._lock:
            self._last_429_at = time.monotonic()

    def in_cooldown(self) -> bool:
        with self._lock:
            if self._last_429_at == 0.0:
                return False
            return (time.monotonic() - self._last_429_at) < config.GEMINI_COOLDOWN_SECONDS

    def reset(self):
        with self._lock:
            self._last_429_at = 0.0


quota_state = _QuotaState()


def is_quota_error(exc: Exception) -> bool:
    text = str(exc)
    return "RESOURCE_EXHAUSTED" in text or "429" in text


def _should_retry(exc: Exception) -> bool:
    return is_quota_error(exc)


# Retries quota errors a small, bounded number of times with exponential
# backoff. Non-quota errors are NOT retried (they bubble up to the caller's
# existing except/fallback logic immediately, as before).
gemini_retry = retry(
    reraise=True,
    stop=stop_after_attempt(config.GEMINI_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.GEMINI_RETRY_BASE_SECONDS, max=10),
    retry=retry_if_exception(_should_retry),
)


def note_failure_if_quota(exc: Exception):
    """Call this in the outer except block of every Gemini call site so the
    cooldown is engaged even after retries are exhausted."""
    if is_quota_error(exc):
        quota_state.mark_exhausted()