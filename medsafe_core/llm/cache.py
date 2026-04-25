"""
In-memory TTL cache for LLM-generated artifacts.

Patient risk profiles, once built, are stable for the session — a patient's
risk factors (eGFR, chronic conditions, active medications, age) don't change
mid-conversation. Caching prevents redundant LLM calls across tool invocations.

Design:
  - TTL-based expiry (default 60 min, enough for a full demo session)
  - Thread-safe via asyncio.Lock (FastMCP can handle concurrent requests)
  - Keyed by patient ID — isolated per patient
  - Explicit invalidation available for testing or refresh

This is a cross-cutting concern, placed in the llm/ module since its primary
purpose is reducing LLM API cost/quota burn.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Async-safe in-memory cache with TTL expiry."""

    def __init__(self, ttl_minutes: int = 60) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._store: dict[str, tuple[T, datetime]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        """Return cached value if fresh, else None."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, stored_at = entry
            if datetime.now(timezone.utc) - stored_at > self._ttl:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: T) -> None:
        """Store a value with the current timestamp."""
        async with self._lock:
            self._store[key] = (value, datetime.now(timezone.utc))

    async def invalidate(self, key: str) -> None:
        """Explicitly remove a cache entry."""
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        """Remove all cache entries."""
        async with self._lock:
            self._store.clear()

    async def stats(self) -> dict:
        """Snapshot of cache state (for debugging/monitoring)."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            fresh = sum(1 for _, ts in self._store.values() if now - ts <= self._ttl)
            return {
                "total_entries": len(self._store),
                "fresh_entries": fresh,
                "stale_entries": len(self._store) - fresh,
                "ttl_minutes": self._ttl.total_seconds() / 60,
            }


# Module-level singleton: patient risk profile cache.
# Keyed by patient_id. Values are JSON strings (the serialized profile).
patient_profile_cache: TTLCache[str] = TTLCache(ttl_minutes=60)
