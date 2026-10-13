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
