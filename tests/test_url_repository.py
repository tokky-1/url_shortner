from sqlalchemy import select

from models.url import URL
from repository import url_repository


def _clicks_in_db(db, url_id: int) -> int:
    """Read clicks straight from Postgres, bypassing the identity map."""
    return db.execute(select(URL.clicks).where(URL.id == url_id)).scalar_one()


def test_create_fetch_then_increment_twice(db):
    created = url_repository.create(db, "https://example.com/one")

    assert created.id is not None
    assert created.clicks == 0, "server_default should seed clicks at 0"

    fetched = url_repository.get_by_id(db, created.id)
    assert fetched is not None
    assert fetched.original_url == "https://example.com/one"

    url_repository.increment_clicks(db, created.id)
    url_repository.increment_clicks(db, created.id)

    assert _clicks_in_db(db, created.id) == 2

    # The ORM read must agree with the database. With synchronize_session=False
    # this returned a stale 0, because get_by_id hands back the identity-mapped
    # instance and nothing had expired it.
    assert url_repository.get_by_id(db, created.id).clicks == 2


def test_two_urls_can_both_sit_at_zero_clicks(db):
    # This is the test that would have failed against clicks = Column(..., unique=True):
    # the second insert would raise IntegrityError because both rows hold 0.
    first = url_repository.create(db, "https://example.com/first")
    second = url_repository.create(db, "https://example.com/second")

    assert first.id != second.id
    assert _clicks_in_db(db, first.id) == 0
    assert _clicks_in_db(db, second.id) == 0
