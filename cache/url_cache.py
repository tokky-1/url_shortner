"""Redis-backed lookup cache for resolved short codes.

The only module that imports `redis`. Everything above it sees two functions
and plain `str` values, so swapping the backing store touches this file alone.

The cache is strictly an optimisation: every `redis.RedisError` is swallowed and
logged, so an outage turns every lookup into a miss and redirects keep working
off Postgres. Nothing here raises.
"""

import logging
import threading
import time
from functools import lru_cache
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from core.config import get_settings

logger = logging.getLogger(__name__)

# Links never change once created, so the TTL is not about correctness - it only
# caps memory. A day is a guess, not a measurement: it assumes a link's clicks
# arrive near the time it is shared, so a day keeps whatever gets traffic
# resident and lets the rest expire, bounding memory to roughly one day of
# distinct links instead of the whole table. Worth revisiting against real hit
# rates once there are some.
TTL_SECONDS = 24 * 60 * 60

# How long to skip Redis after a failure. Without this an outage costs every
# request the full failure latency, and when the failure is DNS - a stopped
# container, measured at 8s per call - socket_connect_timeout does not help,
# because getaddrinfo is a blocking call outside its reach.
BREAKER_SECONDS = 5.0

# 0.0 means healthy: every caller uses Redis via the lock-free path below.
# Any other value is a deadline to skip until.
_skip_cache_until = 0.0

# Guards only the hand-off from "window expired" to "one caller is probing".
# Never held across a Redis call.
_probe_lock = threading.Lock()


def _may_use_cache() -> bool:
    """True if this caller should touch Redis at all.

    While healthy every caller does, and the check is one lock-free float read.

    Once the breaker has tripped, callers skip until the window expires. Then
    exactly one caller is let through, and it re-arms the window *before* it
    goes. That ordering is the whole point: a failure takes 8s to return, so if
    the window were re-armed only afterwards, every request arriving during
    those 8s would see an expired window and pile into Redis together. Under 50
    concurrent requests that is 50 simultaneous 8s stalls, not one.
    """
    global _skip_cache_until

    if _skip_cache_until == 0.0:
        return True

    with _probe_lock:
        now = time.monotonic()
        if now < _skip_cache_until:
            return False
        # Re-arm first, then probe, so nobody follows this caller in.
        _skip_cache_until = now + BREAKER_SECONDS
        return True


def _mark_failed() -> None:
    global _skip_cache_until
    _skip_cache_until = time.monotonic() + BREAKER_SECONDS


def _mark_healthy() -> None:
    global _skip_cache_until
    if _skip_cache_until != 0.0:
        _skip_cache_until = 0.0


@lru_cache
def get_redis() -> redis.Redis:
    """One client for the process, built lazily, like db.connect.get_engine().

    decode_responses=True keeps the str/bytes boundary inside this module so
    callers get `str` back, matching what the database column holds.

    The timeouts matter: without them a hung Redis would block a request for
    the OS default, which is far longer than simply reading Postgres.

    Retries are disabled explicitly. redis-py's `Redis(...)` constructor
    defaults to 10 attempts with exponential backoff - measured at 4.8s for a
    single failed GET - while `from_url` happens to default to none. Relying on
    that difference would mean one refactor away from every redirect stalling
    for seconds during an outage. A cache read is worth one attempt.
    """
    return redis.Redis.from_url(
        get_settings().REDIS_URL,
        decode_responses=True,
        socket_timeout=0.25,
        socket_connect_timeout=0.25,
        retry=Retry(NoBackoff(), 0),
    )


def key(url_id: int) -> str:
    """The cache key for a row id. Single-sourced so tests cannot drift from it."""
    return f"url:{url_id}"


def get(url_id: int) -> str | None:
    """The cached destination for this id, or None if it is not cached.

    Returns None on any Redis failure, so the caller falls through to Postgres.
    """
    if not _may_use_cache():
        return None
    try:
        value = get_redis().get(key(url_id))
    except redis.RedisError as exc:
        _mark_failed()
        # The cause, not a traceback: a stack per call would bury everything
        # else. The breaker keeps this to once per window, not once per request.
        logger.warning(
            "cache unavailable on read, treating as a miss: %s (%s)",
            key(url_id),
            exc,
        )
        return None
    _mark_healthy()
    return value


def put(url_id: int, original_url: str) -> None:
    """Cache this id's destination for TTL_SECONDS.

    Does nothing on any Redis failure: the lookup already succeeded against
    Postgres, so failing to memoise it is not worth failing the request for.
    """
    if not _may_use_cache():
        return
    try:
        get_redis().set(key(url_id), original_url, ex=TTL_SECONDS)
    except redis.RedisError as exc:
        _mark_failed()
        logger.warning(
            "cache unavailable on write, leaving it uncached: %s (%s)",
            key(url_id),
            exc,
        )
        return
    _mark_healthy()
