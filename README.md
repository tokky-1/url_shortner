# URL Shortener

A small URL shortener: `POST /urls` stores a destination and returns a short
code, `GET /{code}` redirects to it and counts the click.

Short codes are base62 encodings of the row's primary key, so no code is ever
stored and no collision check is ever needed — the database's own ID sequence
guarantees uniqueness. The cost of that choice is listed under
[Known gaps](#known-gaps).

Built with FastAPI, SQLAlchemy and Postgres, with Alembic for migrations and
structured JSON logging.

| Method | Path      | Purpose                                             |
| ------ | --------- | --------------------------------------------------- |
| POST   | `/urls`   | Shorten a URL. 201 with `{code, short_url}`.         |
| GET    | `/{code}` | 302 to the original URL, or 404. Increments clicks.  |
| GET    | `/health` | Liveness. Touches nothing.                           |
| GET    | `/ready`  | Readiness. 503 if Postgres is unreachable.           |

## Run

Copy `.env.example` to `.env` and set the database credentials and `BASE_URL`
first — every command below reads it.

With Docker (brings up Postgres, runs the migration, then the app):

```bash
docker compose up --build
```

Locally, against a Postgres you already have running:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

Either way the app listens on port 8000:

```bash
curl -X POST localhost:8000/urls -H 'content-type: application/json' -d '{"url":"https://example.com/page"}'
```

Tests run against a real Postgres (the one in your `.env`), not SQLite and not
mocks. Each test runs inside a transaction that is rolled back, so the database
is left untouched — but the schema must be migrated first:

```bash
uv run pytest
```

## Known gaps

- **No rate limiting.** Anyone can script `POST /urls` and fill the database; the fix belongs at the edge (AWS WAF or ALB rules), not in app code.
- **Sequential IDs are enumerable.** Walking `/1`, `/2`, `/3` reveals every destination — inherent to base62-of-ID, and only a problem if links are meant to be private; a non-sequential code scheme is the fix if that changes.
- **One commit per redirect.** Every redirect does a `SELECT`, an `UPDATE` and a `COMMIT`, which is fine at this size; batching or moving the counter off the request path is the fix when load testing says so.
- **Click counts become best-effort once caching arrives.** A redirect served from a cache never reaches Postgres, so counting has to move off the read path — fire-and-forget increments or a periodic flush — rather than riding along with the lookup.

## Baseline

This is the reference point the next round of work is measured against, so it
is worth being precise about what it does and does not include.

What is in place: the four endpoints above, Alembic-managed schema, base62
codes validated for canonical form (`0abc` and `abc` decode alike, so only the
canonical spelling resolves), URL validation that rejects non-HTTP schemes and
anything over 2048 characters, JSON logs with a per-request ID and query
strings kept out of the logged path, and a container image built once and shared
by the migration and app services.

Verified by 43 tests against real Postgres, covering the codec, the repository,
the service layer, the HTTP routes and the log format.

Not yet measured: no load test has been run, so there are no latency or
throughput numbers here yet. Redis caching, the counter rework and the
enumeration question above are all deferred until there is a measurement to
compare against.
