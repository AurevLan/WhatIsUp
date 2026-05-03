"""Rate limiter singleton (slowapi).

Uses Redis as the storage backend so rate limits are coherent across
multiple server replicas (SC-07). Falls back to in-memory storage if
Redis is unreachable, so a single-instance dev setup keeps working
without a live Redis.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from whatisup.core.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=_settings.redis_url,
    storage_options={"socket_connect_timeout": 2},
    in_memory_fallback_enabled=True,
)
