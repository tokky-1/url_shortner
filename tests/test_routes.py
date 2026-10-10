import pytest
from sqlalchemy import select

from core.codec import decode, encode
from core.config import get_settings
from models.url import URL
from routes.urls import router


def _clicks_in_db(db, url_id: int) -> int:
    return db.execute(select(URL.clicks).where(URL.id == url_id)).scalar_one()


# --- 1. POST a valid URL ---------------------------------------------------


def test_post_valid_url_returns_201_and_short_url(client):
    response = client.post("/urls", json={"url": "https://example.com/page"})

    assert response.status_code == 201
    body = response.json()
    assert body["code"]
    # Host comes from BASE_URL, never a literal in the code.
    assert body["short_url"] == get_settings().short_url(body["code"])
    assert body["short_url"].endswith("/" + body["code"])


# --- 2 and 3. Rejected payloads -------------------------------------------


def test_post_malformed_url_returns_422(client):
    response = client.post("/urls", json={"url": "not a url"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "url_parsing"


def test_post_javascript_scheme_returns_422(client):
    # A javascript: URL stored and later served in a Location header or an
    # href is a stored-XSS vector: every visitor to the short link would
    # execute the attacker's script in this origin's context. HttpUrl allows
    # only http and https, so the payload never reaches the database.
    response = client.post("/urls", json={"url": "javascript:alert(1)"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "url_scheme"


def test_post_url_over_2048_chars_returns_422(client):
    too_long = "https://example.com/" + "a" * (2049 - len("https://example.com/"))

    response = client.post("/urls", json={"url": too_long})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "url_too_long"


# --- 4. Round trip ---------------------------------------------------------


def test_round_trip_post_then_get_redirects(client):
    original = "https://example.com/destination"
    code = client.post("/urls", json={"url": original}).json()["code"]

    response = client.get(f"/{code}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == original


# --- 5. Unknown code ------------------------------------------------------


def test_get_unknown_code_returns_404(client):
    response = client.get(f"/{encode(999999)}", follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["detail"] == "short code not found"


@pytest.mark.parametrize("code", ["abc!", "z" * 30])
def test_get_unresolvable_code_returns_404_not_500(client, code):
    # Bad characters and an out-of-range decoded ID are both just "not found".
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404


# --- 6. Probes, and the route-order trap ----------------------------------


def test_health_returns_200_without_touching_the_database(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_database_reachable(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_probe_paths_are_valid_base62_so_order_matters():
    # This is why the ordering test below exists: both probe paths decode
    # cleanly as short codes, so GET /{code} would gladly claim them.
    assert decode("health") > 0
    assert decode("ready") > 0


def test_probes_are_registered_before_the_catch_all_code_route():
    paths = [route.path for route in router.routes]

    assert paths.index("/health") < paths.index("/{code}")
    assert paths.index("/ready") < paths.index("/{code}")


# --- 7. Click counting through the HTTP layer -----------------------------


def test_two_redirects_record_two_clicks_in_the_database(client, db):
    code = client.post("/urls", json={"url": "https://example.com/counted"}).json()["code"]

    client.get(f"/{code}", follow_redirects=False)
    client.get(f"/{code}", follow_redirects=False)

    # Read the database, not the response body.
    assert _clicks_in_db(db, decode(code)) == 2


def test_ready_returns_503_when_database_unreachable():
    """The failure half of the readiness probe.

    Uses its own override rather than the client fixture, because the point
    is a session whose SELECT 1 raises.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    from db.connect import get_db
    from main import app

    class UnreachableSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def rollback(self):
            pass

    app.dependency_overrides[get_db] = UnreachableSession
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
