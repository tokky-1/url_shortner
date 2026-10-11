import pytest
from sqlalchemy import select

from core.codec import encode
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
