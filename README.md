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
- **Click counting keeps the write on the request path.** Decided rather than outstanding: see [Caching](#caching). Counts stay exact, at the cost of a cache hit still doing an `UPDATE` and a `COMMIT`, so the cache removes the `SELECT` and nothing else.

## Caching

A Redis lookup cache in front of `GET /{code}`. `cache/url_cache.py` is the only
module that imports `redis`; the service decides when to use it, and the route
and repository know nothing about it.

- Key `url:{id}`, value the destination URL, TTL 24 hours. Links never change,
  so the TTL caps memory rather than protecting correctness: short-link traffic
  is front-loaded, so a day keeps the set that gets traffic resident and lets
  the long tail expire.
- **A miss is never cached.** Caching a "not found" would hide a link created a
  second after the failed lookup until the TTL expired.

### Click counting

Option A of three: **every redirect still runs the `UPDATE`, so counts stay
exact.** The alternatives were an `INCR` in Redis flushed to Postgres
periodically, and fire-and-forget increments.

What that costs:

- The cache removes the `SELECT`, not the write. A hit is a Redis `GET` plus
  `UPDATE` and `COMMIT`; a miss is a `GET`, a `SELECT`, an `UPDATE`, a `COMMIT`
  and a Redis `SET` - marginally more work than before the cache existed.
- Postgres stays on the request path for every redirect, so the cache buys
  latency, not availability. A cached link still cannot be served while Postgres
  is down, which is why `/ready` checks Postgres.
- Hot keys gain little. The measured hot-mode bottleneck was
  `Lock: transactionid` on one row's `UPDATE`, and this option keeps that write,
  so expect `spread` to improve while `hot` stays roughly flat.
- Every redirect still needs a pooled connection and a write transaction, so the
  connection arithmetic in the baseline is unchanged.

Option B is worth revisiting only if a load test shows the `UPDATE` has become
the limit; it trades exact counts for increments lost between flushes.

### Prediction, written before the After run

One worker, 50 VUs, so it compares against the baseline above. Recorded before
measuring, so a wrong prediction stays on the record.

| Mode | Baseline rps | Predicted rps | Predicted p95 |
| ------ | -----------: | ------------: | ------------: |
| spread | 193.8        | 270-300 (point estimate 285) | 250-300 ms |
| hot    | 187.9        | 190-220 (point estimate 205) | 400-450 ms |

Reasoning. A redirect costs 6.51ms of app CPU against 0.85ms of Postgres CPU, and
`/health` sets a 1.17ms floor for framework plus logging, so about 5.3ms is Python
work around two statements. The cache removes one of them - the ORM `SELECT` and
the row materialisation behind `get_by_id` - and replaces it with a Redis `GET`
that returns a ready string. Guessing that SELECT at roughly 2.2ms of the 5.3ms
puts a redirect near 4.3ms, and since the app is pinned at about one core,
throughput should scale by 6.51/4.3, which is 193.8 -> ~293. Call it 285 because
each run seeds 1000 fresh codes, so the first ~1000 requests are misses that cost
slightly more than the baseline did.

`hot` should barely move. Its measured bottleneck was `Lock: transactionid`, with
9-12 sessions blocked on one row's `UPDATE`, and option A keeps that `UPDATE`.
Removing the `SELECT` does not relieve a row lock, so any gain comes only from
cheaper lookups between lock waits.

If the gain is small, that is the result: it would mean the cost sits in the write
and the commit, not the read, and option B becomes the next lever.

### When Redis is unavailable

Every `redis.RedisError` is caught in `url_cache`, logged at WARNING, and turned
into a miss, so redirects keep working off Postgres. Two details that are easy to
get wrong:

- `socket_connect_timeout` does not bound DNS. With the container stopped,
  `getaddrinfo("redis")` alone took 8s, so a redirect cost 16s - a 302 that is
  an outage in practice. A 5-second breaker (`BREAKER_SECONDS`) means one request
  per window pays that and the rest skip Redis entirely.
- Retries are disabled explicitly. redis-py's `Redis(...)` constructor defaults
  to 10 attempts with backoff, measured at 4.8s for one failed `GET`, while
  `from_url` defaults to none - too sharp a difference to leave implicit.

`/ready` deliberately does **not** check Redis. Readiness decides whether the
load balancer sends traffic; since a cache outage only slows things down, and the
cache is shared by every task, failing readiness on it would pull the whole
service out at once and turn a slower service into no service.

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

### Measured

app CPU-bound at ~220 req/s, one worker, Postgres at 16-28%.

k6, `constant-vus`, 30s per run, one uvicorn worker, image
`urlshortener:local` (`802705e885e3`), built from tag `v1-postgres` (`a569347`) -
the only commit after that tag changes this README, so the runtime code measured
here is exactly `v1-postgres`. Each variation was run twice; the figures below are
the second run. Every run returned 302 for every redirect with zero failures.
Latencies are milliseconds.

The Redis comparison is run at **one worker**, matching this baseline. Compose
briefly ran `--workers 4` while the worker question was being measured; four
workers roughly doubles `spread` throughput, so mixing it with the cache change
would move two variables at once and the comparison would mean nothing.

Each run seeds its own 1000 codes, so `urls` grew as the matrix progressed: from
about 1,000 rows at the start to 67,003 at the end of the single-worker runs, and
91,004 after the later four-worker runs. Every redirect looks up by primary key,
so the row count does not move the numbers.

**Spread** - each request resolves a random code out of 1000.

| VUs | Throughput (req/s) | p50 | p95 | p99 | max |
| --: | -----------------: | --: | --: | --: | --: |
| 5   | 261.4              | 18.3  | 25.5  | 34.0  | 57.8  |
| 10  | 215.8              | 44.3  | 65.6  | 86.7  | 125.6 |
| 25  | 152.8              | 144.5 | 306.0 | 397.7 | 658.2 |
| 50  | 193.8              | 246.1 | 390.4 | 473.9 | 670.2 |
| 100 | 211.9              | 470.6 | 592.7 | 650.5 | 752.1 |

**Hot** - every request resolves the same code.

| VUs | Throughput (req/s) | p50 | p95 | p99 | max |
| --: | -----------------: | --: | --: | --: | --: |
| 5   | 221.5              | 20.5  | 36.4  | 54.5    | 102.0   |
| 10  | 220.6              | 41.0  | 80.4  | 110.3   | 199.7   |
| 25  | 185.1              | 116.4 | 279.9 | 408.7   | 790.1   |
| 50  | 187.9              | 250.6 | 450.6 | 576.3   | 1,031.9 |
| 100 | 178.9              | 523.1 | 867.5 | 1,038.9 | 1,429.8 |

Throughput never climbs across 5-100 VUs: it is already flat. A 1-5 VU sweep
(three runs each) shows it saturated by 2 to 3 VUs, which is exactly where the app
process reaches one full core:

| VUs | Throughput (req/s) | p50 | p95 | `app` CPU |
| --: | -----------------: | --: | --: | --------: |
| 1   | 131.1              | 7.0  | 10.5 | 50%  |
| 2   | 213.1              | 8.4  | 13.9 | 83%  |
| 3   | 228.3              | 11.4 | 23.3 | 100% |
| 4   | 222.4              | 15.9 | 32.1 | 111% |
| 5   | 216.9              | 21.4 | 34.1 | 116% |

Past the knee only latency grows. `throughput x mean latency = VUs` holds to
within 1% on all 20 rows above, so once the service rate is pinned, latency is
just queue depth divided by a constant.

**`GET /health`** - same FastAPI, middleware and logging cost, no database work,
so its rate is the ceiling any cache in front of Postgres could approach. Three
runs each, mean:

| VUs | Throughput (req/s) | p50  | p95  | `app` CPU | `db` CPU |
| --: | -----------------: | ---: | ---: | --------: | -------: |
| 3   | 807.6              | 3.2  | 6.2  | 93.4%     | 0.0%     |
| 50  | 896.5              | 52.7 | 84.8 | 105.1%    | 0.0%     |

`/health` also saturates at about one core, so the one-worker ceiling is
universal; it serves ~4x the traffic only because each request is ~4x cheaper.
Per-request app CPU is 1.17ms for `/health` against 6.51ms for a redirect at 50
VUs, so the framework is only ~18% of the cost and the rest is the ORM and the
database work.

With `echo=True` on the engine, one redirect issues exactly two statements in one
transaction:

```sql
SELECT urls.id, urls.original_url, urls.clicks, urls.created_at
  FROM urls WHERE urls.id = %(id_1)s LIMIT 1;
UPDATE urls SET clicks = (urls.clicks + 1)
  WHERE urls.id = %(id_1)s RETURNING urls.id;
```

then one `COMMIT`. On Postgres with SQLAlchemy 2.1, `synchronize_session="fetch"`
is satisfied by that `RETURNING` clause, so it costs no extra SELECT.

Under `hot`, `pg_stat_activity` showed `Lock: transactionid` in 8 of 8 samples
with 9-12 sessions blocked, against 0 of 8 under `spread`: every VU serialises on
one row's UPDATE, so effective concurrency on that row is 1.

Still deferred: Redis caching and the counter rework now have a number to beat,
and the enumeration question is unchanged.
