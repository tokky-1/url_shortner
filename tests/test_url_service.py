import inspect

import pytest
from sqlalchemy import delete, select

from core.codec import decode, encode
from core.exceptions import URLNotFoundError
from models.url import URL
from services import url_service


def _clicks_in_db(db, url_id: int) -> int:
    """Read clicks straight from Postgres, not from the identity map."""
    return db.execute(select(URL.clicks).where(URL.id == url_id)).scalar_one()


def test_create_then_resolve_returns_original_url(db):
    code = url_service.create_short_url(db, "https://example.com/landing")

    assert url_service.resolve(db, code) == "https://example.com/landing"


def test_resolve_twice_records_two_clicks(db):
    code = url_service.create_short_url(db, "https://example.com/counted")

    url_service.resolve(db, code)
    url_service.resolve(db, code)

    # Re-read from the database rather than trusting the in-memory object.
    url_id = db.execute(
        select(URL.id).where(URL.original_url == "https://example.com/counted")
    ).scalar_one()
    assert _clicks_in_db(db, url_id) == 2


def test_valid_code_with_no_row_raises_not_found(db):
    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, encode(999999))


def test_code_with_invalid_character_raises_not_found(db):
    # Must be URLNotFoundError, not the ValueError the codec raises.
    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, "abc!")


def test_absurdly_long_code_raises_not_found(db):
    # 30 "z" chars decodes to roughly 5.9e53, far past the bigint column.
    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, "z" * 30)


def test_non_canonical_code_with_leading_zero_raises_not_found(db):
    # "0" + code decodes to the same ID, but only one spelling may resolve:
    # without the canonical-form check in resolve(), this would be a second
    # working URL for the same row.
    code = url_service.create_short_url(db, "https://example.com/canonical")

    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, "0" + code)


# --- caching ---------------------------------------------------------------


def test_first_resolve_populates_the_cache(db, redis_cache):
    code = url_service.create_short_url(db, "https://example.com/warm")

    url_service.resolve(db, code)

    assert redis_cache.get(f"url:{decode(code)}") == "https://example.com/warm"


def test_second_resolve_is_served_from_the_cache(db, redis_cache):
    code = url_service.create_short_url(db, "https://example.com/cached")
    url_id = decode(code)
    url_service.resolve(db, code)

    # Drop the row. A resolve that still returns the URL can only have come
    # from the cache, which proves the hit path without mocking the repository.
    db.execute(delete(URL).where(URL.id == url_id))

    assert url_service.resolve(db, code) == "https://example.com/cached"


def test_a_miss_is_never_cached(db, redis_cache):
    # Rule: caching a "not found" would hide a link created a second later
    # until the TTL expired.
    url_id = 10_000_003

    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, encode(url_id))

    assert redis_cache.get(f"url:{url_id}") is None
    assert redis_cache.dbsize() == 0, "a miss must leave the cache untouched"


def test_an_invalid_code_is_never_cached(db, redis_cache):
    for bad in ("abc!", "z" * 30):
        with pytest.raises(URLNotFoundError):
            url_service.resolve(db, bad)

    assert redis_cache.dbsize() == 0


def test_cached_resolve_still_counts_the_click(db, redis_cache):
    code = url_service.create_short_url(db, "https://example.com/still-counted")
    url_id = decode(code)

    url_service.resolve(db, code)  # miss
    url_service.resolve(db, code)  # hit
    url_service.resolve(db, code)  # hit

    # Caching the lookup must not quietly stop counting clicks.
    assert _clicks_in_db(db, url_id) == 3


def test_route_and_repository_know_nothing_about_redis():
    # Rule: the service orchestrates. Only it may know a lookup has two sources.
    from repository import url_repository
    from routes import urls as url_routes

    for module in (url_routes, url_repository):
        source = inspect.getsource(module)
        assert "redis" not in source.lower(), f"{module.__name__} imports redis"
        assert "url_cache" not in source, f"{module.__name__} uses the cache directly"


def test_cache_hit_does_not_call_the_repository(db, redis_cache, monkeypatch):
    code = url_service.create_short_url(db, "https://example.com/spied")
    real_get_by_id = url_service.get_by_id
    calls: list[int] = []

    def counting_get_by_id(session, url_id):
        calls.append(url_id)
        return real_get_by_id(session, url_id)

    # The service imports get_by_id by name, so patch the binding it actually
    # calls, not the one in repository.url_repository.
    monkeypatch.setattr(url_service, "get_by_id", counting_get_by_id)

    assert url_service.resolve(db, code) == "https://example.com/spied"
    assert len(calls) == 1, "the first resolve is a miss and must read Postgres"

    assert url_service.resolve(db, code) == "https://example.com/spied"
    assert len(calls) == 1, "the second resolve must be served from the cache"


def test_a_miss_is_not_remembered_so_a_link_created_later_resolves(db, redis_cache):
    # The point of never caching a "not found": the link below is created after
    # the failed lookup, and must be visible at once rather than after the TTL.
    url_id = 10_000_007
    code = encode(url_id)

    with pytest.raises(URLNotFoundError):
        url_service.resolve(db, code)

    db.add(URL(id=url_id, original_url="https://example.com/created-later"))
    db.flush()

    assert url_service.resolve(db, code) == "https://example.com/created-later"
