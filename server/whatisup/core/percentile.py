"""Streaming percentile helpers backed by T-Digest.

Used by the Global Health Engine to maintain rolling p50/p95/p99 over long
windows (1 h / 6 h / 24 h) without keeping every sample. The 5-minute window
is computed exactly from the recent CheckResults, not via T-Digest.

Why T-Digest: bounded memory (~1 KB per digest at 100 centroids), accurate at
the tails (p95/p99), mergeable across workers if we ever fan out ingest.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_CENTROIDS = 100


def _make_digest():
    """Lazily instantiate a TDigest. Raises ImportError if pytdigest is absent."""
    from pytdigest import TDigest  # type: ignore[import]

    return TDigest(compression=_MAX_CENTROIDS)


def serialize(digest) -> bytes:
    return digest.get_centroids().tobytes()


def deserialize(blob: bytes | None):
    digest = _make_digest()
    if not blob:
        return digest
    import numpy as np  # type: ignore[import]

    arr = np.frombuffer(blob, dtype=float).reshape(-1, 2)
    if arr.size:
        digest.update(arr[:, 0], weights=arr[:, 1])
    return digest


def update(blob: bytes | None, samples: list[float]) -> bytes:
    """Merge ``samples`` into the digest in ``blob`` and return the new blob."""
    if not samples:
        return blob or b""
    digest = deserialize(blob)
    digest.update(samples)
    return serialize(digest)


def quantile(blob: bytes | None, q: float) -> float | None:
    if not blob:
        return None
    digest = deserialize(blob)
    try:
        return float(digest.inverse_cdf(q))
    except Exception:
        return None
