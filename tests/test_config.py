import pytest

from core.config import Settings


def _settings(base_url: str) -> Settings:
    """Settings built from literals, so .env cannot change the result."""
    return Settings(
        DB_HOST="localhost",
        DB_PORT=5432,
        DB_USER="postgres",
        DB_PASSWORD="change-me",
        DB_NAME="url_short_db",
        BASE_URL=base_url,
    )


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8000", "http://localhost:8000/", "http://localhost:8000///"],
)
def test_short_url_joins_with_exactly_one_slash(base_url):
    # A BASE_URL with a trailing slash is the normal way to write it in an
    # env file, and naive f-string joining would hand out
    # "http://localhost:8000//abc" - a different path that most servers do
    # not treat as equivalent.
    assert _settings(base_url).short_url("abc") == "http://localhost:8000/abc"


def test_short_url_keeps_a_base_path():
    assert _settings("https://short.test/go").short_url("abc") == (
        "https://short.test/go/abc"
    )


def test_db_url_percent_encodes_credentials():
    settings = Settings(
        DB_HOST="db",
        DB_PORT=5432,
        DB_USER="user@corp",
        DB_PASSWORD="p@ss/word:1",
        DB_NAME="url_short_db",
        BASE_URL="http://localhost:8000",
    )

    # Unescaped "@" or "/" in the password would truncate the host or the
    # database name when SQLAlchemy parses the URL.
    assert settings.DB_URL == (
        "postgresql://user%40corp:p%40ss%2Fword%3A1@db:5432/url_short_db"
    )
