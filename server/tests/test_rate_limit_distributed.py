"""SC-07 — Verify the slowapi limiter is wired to Redis with memory fallback."""

from __future__ import annotations

from whatisup.core.limiter import limiter


def test_limiter_storage_uri_is_redis() -> None:
    """The limiter must use the configured Redis URL as its storage backend."""
    # slowapi exposes the underlying limits storage via _storage on each Limiter.
    storage = limiter._storage
    assert storage is not None
    # The Redis-backed storage class is from the `limits` package — assert that
    # its module path mentions redis (rather than memory) so a regression to
    # MemoryStorage would break the test.
    storage_module = storage.__class__.__module__
    assert "redis" in storage_module.lower(), (
        f"expected Redis storage, got {storage.__class__!r} from module {storage_module!r}"
    )


def test_limiter_has_memory_fallback_enabled() -> None:
    """If Redis goes away, the limiter must keep working in-memory rather than 500."""
    # slowapi stores this on the Limiter instance.
    assert getattr(limiter, "_in_memory_fallback_enabled", False) is True


def test_limiter_default_limits_present() -> None:
    """A baseline default limit must be configured so endpoints without an
    explicit @limiter.limit decorator still get protected."""
    assert limiter._default_limits, "default_limits must be set"
