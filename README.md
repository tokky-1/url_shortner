# URL Shortener

`POST /urls` stores a long URL and gives back a short code. `GET /{code}` sends
the visitor to the long URL and counts the click.

Built with FastAPI, Postgres, Redis (as a cache), Alembic and JSON logs.

| Method | Path      | What it does                                   |
| ------ | --------- | ---------------------------------------------- |
| POST   | `/urls`   | Shorten a URL. Returns `{code,short_url}`.    |
| GET    | `/{code}` | Redirect (302) to the original URL, or 404.    |
| GET    | `/health` | Is the process up? Touches nothing.            |
| GET    | `/ready`  | Can it reach Postgres? 503 if not.             |

## Run

Copy `.env.example` to `.env` and fill it in, then:

```bash
docker compose up --build      # Postgres, Redis, migration, app
```

Without Docker (needs Postgres and Redis already running):

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
uv run pytest                  # tests use real Postgres and real Redis
```

## How it works

**Codes.** The code is the row's database ID written in base62 (`10` becomes
`A`, `61` becomes `z`, `62` becomes `10`). Nothing extra is stored, and two
links can never get the same code because the database never repeats an ID. Only the canonical spelling
works: `/0abc` is rejected even though it decodes like `/abc`.

**Layers.** Routes handle HTTP only. Services hold the logic. Repositories talk
to Postgres. `cache/url_cache.py` is the only file that talks to Redis.

**Cache.** On a redirect the service checks Redis first. On a miss it reads
Postgres and stores the answer for 24 hours (a guess, not a measured value).
"Not found" is never cached, so a link created a second later still works.

**Clicks.** Every redirect still does an `UPDATE` in Postgres, so counts stay
exact. The cache only removes the `SELECT`.

**If Redis goes down,** redirects still work, just from Postgres. Two traps made
this harder than a `try/except`:

- Looking up the Redis hostname can block for 8 seconds, and the connection
  timeout does not cover that. So after a failure the app skips Redis for 5
  seconds, and only one request at a time is allowed to test it again.
- redis-py retries 10 times by default in one constructor, so retries are
  switched off explicitly.

With Redis stopped at 50 users, the first version fell to 108 req/s with
p99 = 8.2s. The fixed version runs at 222-370 req/s with p99 = 0.3-0.5s. A test
(`test_only_one_thread_probes_when_the_window_expires`) guards the fix.

`/ready` does not check Redis. A cache outage makes the app slower, not wrong,
and failing readiness would pull every instance out at once.

## Load test results

k6, 30 seconds per run, 4 uvicorn worker. 
"Spread" means 1000 different codes.
"Hot" means every request uses the same code.

**1. 4 worker tops out near 220 req/s.** That limit is reached with just 2-3
users. After that, more users only wait in line: at 50 users each request waits
about 50 x 4.5ms = ~250ms. The app process was at about 100% of one core while
Postgres used only 16-28% of one core.

| Users | Spread req/s | Spread p95 | Hot req/s | Hot p95 |
| ----: | -----------: | ---------: | --------: | ------: |
| 5     | 261          | 26 ms      | 222       | 36 ms   |
| 50    | 194          | 390 ms     | 188       | 451 ms  |
| 100   | 212          | 593 ms     | 179       | 868 ms  |

**2. A redirect costs 6.5ms of app CPU. `/health` costs 1.2ms.** `/health` does
about 800-900 req/s, so that is the most any cache could ever reach.

**3. Hot codes queue on one database row.** During hot runs Postgres showed
`Lock: transactionid` in 8 of 8 samples (0 of 8 during spread).

**4. Redis helped a little.** Same-session comparison, three runs each, cache
off against cache on:

| Mode   | Cache off | Cache on | Change |
| ------ | --------: | -------: | -----: |
| Spread | 168 req/s | 188      | +12%   |
| Hot    | 161 req/s | 179      | +11%   |

Single runs swung from -31% to +51%, so read this as "small and positive", not
as a precise number. I predicted 285 req/s for spread and was wrong. The
`SELECT` that the cache removes was worth only 0.5-0.7ms, not the 2.2ms I
guessed.

**Best guess for the remaining time** (a hypothesis, not measured): most of the
~5ms left is Python work around the `UPDATE` and `COMMIT` and getting a database
connection. `pool_pre_ping=True` adds one round trip per connection and is an
unmeasured suspect. Profile before changing anything.

Measured on tag `v1-postgres` (`a569347`, image `802705e885e3`) and, for the
cache runs, commit `58ab288` (image `c237a07a74e5`). Rows in `urls` grew from
1,000 to about 100,000 during testing; the cache comparison was run after
`VACUUM` and against a control to cancel that drift.

## Known gaps

- **No rate limiting.** Anyone can script `POST /urls` and fill the database.
  Fix at the edge (AWS WAF or ALB rules), not in app code.
- **Codes can be guessed.** `/1`, `/2`, `/3` reveal every link. Fine for public links; a problem for private ones.
- **Every redirect writes to Postgres.** Moving the click counter off the
  request path (count in Redis, save to Postgres in batches) is the next idea. The cost is lost counts if Redis dies between saves.
- **The Redis safety check is per worker.** With 4 workers there are 4 separate
  checks, and the very first failure still hits every in-flight request once.
- **The 24 hour cache time is a guess.** Revisit it with real hit rates.