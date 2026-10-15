import threading
import time

import redis

from cache import url_cache

# conftest's autouse `redis_cache` fixture points these at a throwaway logical
# DB and flushes it either side, so they hit a real Redis and leave nothing.
_PROBE_ID = 10_000_001


def test_put_then_get_round_trips():
    url_cache.put(_PROBE_ID, "https://example.com/cached")
    value = url_cache.get(_PROBE_ID)

    assert value == "https://example.com/cached"
    # decode_responses=True, or this would be bytes and every caller would have
    # to know it.
    assert isinstance(value, str)


def test_missing_key_returns_none():
    assert url_cache.get(_PROBE_ID + 1) is None


def test_put_applies_the_ttl():
    url_cache.put(_PROBE_ID + 2, "https://example.com/expiring")

    # Without ex=, Redis reports -1 for "no expiry", so this pins the TTL choice.
    ttl = url_cache.get_redis().ttl(url_cache.key(_PROBE_ID + 2))
    assert 0 < ttl <= url_cache.TTL_SECONDS


def test_key_scheme():
    assert url_cache.key(42) == "url:42"


def test_only_one_thread_probes_when_the_window_expires(monkeypatch):
    """Exactly one caller may probe a failed cache, however many arrive at once.

    `_may_use_cache` re-arms the window *before* probing. With the re-arm after
    the call instead, every caller arriving during the failure sees an expired
    window and enters Redis together - 20 callers, 20 concurrent stalls - which
    is what made a Redis outage collapse throughput under load.
    """
    calls: list[int] = []
    counter_lock = threading.Lock()

    class SlowFailing:
        def get(self, _key):
            with counter_lock:
                calls.append(1)
            time.sleep(0.5)
            raise redis.ConnectionError("simulated outage")

    monkeypatch.setattr(url_cache, "get_redis", lambda: SlowFailing())
    # Tripped earlier, window just expired: the exact state the bug lived in.
    monkeypatch.setattr(url_cache, "_skip_cache_until", time.monotonic() - 0.01)

    threads = [
        threading.Thread(target=url_cache.get, args=(i,)) for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"expected exactly one probe, got {len(calls)}"
