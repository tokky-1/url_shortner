import pytest
from sqlalchemy.orm import Session

from db.connect import get_engine


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
