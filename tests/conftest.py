import pytest
import redis as redis_lib
from sqlalchemy.orm import Session

from db.connect import get_engine


@pytest.fixture(autouse=True)
def redis_cache(monkeypatch):
    """Point the cache at a throwaway Redis logical DB, flushed either side.

    The `db` fixture rolls Postgres back with savepoints, but Redis has no
    transactions: without this, every id written by a rolled-back test would
    linger in the dev cache, so the suite would not leave the stores as it
    found them. Autouse because `resolve()` now writes to the cache on every
    miss, so any test touching the service touches Redis.
    """
    from cache import url_cache
    from core.config import get_settings

    # A previous test may have tripped the breaker; each test starts closed.
    monkeypatch.setattr(url_cache, "_skip_cache_until", 0.0)

    base = get_settings().REDIS_URL.rpartition("/")[0]
    client = redis_lib.Redis.from_url(f"{base}/15", decode_responses=True)
    monkeypatch.setattr(url_cache, "get_redis", lambda: client)

    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture(scope="session")
def engine():
    return get_engine()


@pytest.fixture
def db(engine):
    """A real Postgres session that leaves nothing behind.

    The session joins an outer transaction using savepoints, so the commits
    inside the repository run for real - server defaults apply and
    constraints fire - but the outer rollback discards everything, so the
    dev database is untouched.

    expire_on_commit mirrors db.connect.get_session_factory() so these tests
    exercise the same session behaviour the app uses.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db):
    """TestClient whose get_db dependency yields the rollback-isolated session.

    Everything the endpoints write goes through the same savepoint session as
    the other tests, so requests hit real Postgres and still leave nothing
    behind.
    """
    from fastapi.testclient import TestClient

    from db.connect import get_db
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
