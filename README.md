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

### After Redis

Measured on commit `58ab288`, image `c237a07a74e5`, one worker, 50 VUs, 30s runs.

**The baseline above is not a valid "before" any more.** By the time the cache
existed, `urls` held 102,008 rows against 1,000-67,000 during the baseline,
autovacuum had never run (`autovacuum_count = 0`) and the table was 17.1% dead
tuples. Comparing against it measures table bloat as much as caching. For the
record, the raw numbers are `spread` 162.9 rps and `hot` 161.4 rps as means of
three - both *below* the 193.8 and 187.9 baselines, which is drift, not the cache.

So the real comparison is a same-session control: `VACUUM (ANALYZE) urls` first,
then a second container on the same image with `REDIS_URL` pointed at a dead port,
so every lookup fails in about 1ms and the app runs the pure Postgres path with
identical code (1000 cache calls cost 1.4ms total once the breaker trips). Runs
alternate between the two arms so drift cannot favour either.

| spread pair | cache off | cache on | delta |
| ----------: | --------: | -------: | ----: |
| 1           | 170.9     | 180.6    | +6%   |
| 2           | 130.2     | 183.2    | +41%  |
| 3           | 203.1     | 200.8    | -1%   |
| **mean**    | **168.1** | **188.2** | **+12.0%** |

| hot pair | cache off | cache on | delta |
| -------: | --------: | -------: | ----: |
| 1        | 177.5     | 206.4    | +16%  |
| 2        | 159.3     | 109.2    | -31%  |
| 3        | 146.4     | 220.4    | +51%  |
| **mean** | **161.1** | **178.7** | **+10.9%** |

p95 means: `spread` 448ms to 401ms, `hot` 540ms to 550ms.

**Prediction versus result.** Predicted `spread` 270-300, measured 188.2.
Predicted `hot` 190-220, measured 178.7. The `spread` prediction was wrong by a
third, and the reasoning behind it was wrong too: it assumed the ORM `SELECT` was
worth about 2.2ms of the 5.3ms non-framework budget. Per-request app CPU says
otherwise:

| | app CPU per redirect |
| ----------------- | -------------------: |
| spread, cache off | 7.32 ms |
| spread, cache on  | 6.85 ms |
| hot, cache off    | 7.01 ms |
| hot, cache on     | 6.27 ms |

The `SELECT` was worth **0.5-0.7ms, not 2.2ms** - roughly 4x less than assumed.
`hot` also gained about as much as `spread` (+11% against +12%), where the
prediction said it would gain clearly less.

Caveat on all of it: individual pair deltas run from -31% to +51%, so with three
pairs the noise is larger than the effect. Treat +11% as "small and positive",
not as a measured constant.

**What this actually settles.** Of roughly 7ms of app CPU per redirect, about
1.17ms is framework and logging, about 0.5ms was the `SELECT` the cache removed,
and the remaining ~5ms is the write path: the `UPDATE`, the `COMMIT`, the session
and the connection checkout. The cache took the small half. That answers the
option B question directly - the write is now the limit, so moving the counter
off the request path is the next lever, not a bigger cache.

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
