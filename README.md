# Product Catalog API

A backend service for browsing a catalog of ~200,000 products, newest
first, with category filtering and **cursor-based (keyset) pagination**
that stays correct even while products are being added or updated by
other users in real time.

Built with **FastAPI**, **PostgreSQL**, **SQLAlchemy**, and **Pydantic**.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Local Setup](#local-setup)
3. [Database Setup](#database-setup)
4. [Running Locally](#running-locally)
5. [Seeding 200,000 Products](#seeding-200000-products)
6. [API Examples](#api-examples)
7. [Design Decisions](#design-decisions)
8. [Why Cursor Pagination Instead of OFFSET](#why-cursor-pagination-instead-of-offset)
9. [Database Indexing](#database-indexing)
10. [Deploying on Render](#deploying-on-render)
11. [Setting Up Neon PostgreSQL](#setting-up-neon-postgresql)
12. [Future Improvements](#future-improvements)

---

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app instance, middleware, router registration
│   ├── database.py      # SQLAlchemy engine, session factory, get_db() dependency
│   ├── models.py         # Product ORM model + indexes
│   ├── schemas.py        # Pydantic request/response schemas
│   ├── crud.py           # Cursor pagination logic and DB queries
│   └── routes.py         # API endpoint definitions
├── scripts/
│   ├── __init__.py
│   ├── create_tables.py  # One-time script to create tables/indexes
│   └── seed.py            # Generates and bulk-inserts 200,000 fake products
├── requirements.txt
├── .env.example
├── .gitignore
├── render.yaml            # Render deployment config (infrastructure-as-code)
└── README.md
```

**Why this structure?** Each file has exactly one job:

- `models.py` only knows about the database schema.
- `schemas.py` only knows about the public API contract (JSON in/out).
- `crud.py` only knows how to query the database.
- `routes.py` only knows how to wire HTTP requests to `crud.py` and shape
  responses using `schemas.py`.
- `main.py` only knows how to assemble the app.

This separation means you can change the database schema without
touching the API contract, swap the database engine without touching
route logic, and unit test `crud.py` without spinning up FastAPI at all.

---

## Local Setup

### Prerequisites

- Python 3.11 or newer
- PostgreSQL 14 or newer (running locally, or a remote URL like Neon — see
  below)
- `pip`

### 1. Clone and create a virtual environment

```bash
cd backend
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set `DATABASE_URL` to point at your PostgreSQL instance
(local or Neon — see [Database Setup](#database-setup) below).

---

## Database Setup

### Option A: Local PostgreSQL

```bash
# Create the database (run once)
createdb productdb

# In .env:
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/productdb
```

(Adjust the username/password to match your local PostgreSQL install.)

### Option B: Neon PostgreSQL (managed, free tier, recommended)

See the full [Setting Up Neon PostgreSQL](#setting-up-neon-postgresql)
section below. In short: create a Neon project, copy its connection
string into `DATABASE_URL` in `.env`, and continue below — the rest of
the setup is identical regardless of which Postgres you use.

### Create the tables

Once `DATABASE_URL` is set, create the `products` table and its indexes:

```bash
python -m scripts.create_tables
```

You should see:
```
Creating tables (if they do not already exist)...
Done. Tables and indexes are ready.
```

---

## Running Locally

```bash
uvicorn app.main:app --reload
```

- API root: http://127.0.0.1:8000/
- Interactive docs (Swagger UI): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

`--reload` auto-restarts the server on code changes — useful for
development, but should NOT be used in production (see `render.yaml`,
which omits it).

---

## Seeding 200,000 Products

After tables are created, generate the demo dataset:

```bash
python -m scripts.seed
```

This will print progress as it inserts in batches:
```
Seeding 200,000 products in batches of 5,000...
  Inserted 5,000 / 200,000
  Inserted 10,000 / 200,000
  ...
Done. Seeding complete.
```

On a typical local Postgres instance this finishes in well under a
minute. Against a remote database (like Neon's free tier) it may take a
few minutes due to network latency per batch — this is expected and is
still vastly faster than row-by-row insertion would be (see
`scripts/seed.py`'s docstring for the full explanation of why bulk
insertion is used).

You can tune the size/speed via environment variables (see
`.env.example`):
```bash
SEED_TOTAL_PRODUCTS=200000   # total rows to generate
SEED_BATCH_SIZE=5000          # rows per INSERT statement
```

---

## API Examples

### Health check

```bash
curl http://127.0.0.1:8000/health
```
```json
{ "status": "ok", "database": "connected" }
```

### First page of products (newest first)

```bash
curl "http://127.0.0.1:8000/products?limit=5"
```
```json
{
  "items": [
    {
      "id": "8f14e45f-ceea-467e-b9c8-19e1b1c4d6f1",
      "name": "Initech Vivid Smartwatch",
      "category": "Electronics",
      "price": "245.99",
      "created_at": "2026-06-22T18:03:11.482310+00:00",
      "updated_at": "2026-06-22T18:03:11.482310+00:00"
    }
    // ... 4 more items
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0IjogIjIwMjYtMDYtMjJUMTc6NTk6MDIuMTAyMzQ1KzAwOjAwIiwgImlkIjogIjNkNTk5...",
  "has_more": true
}
```

### Next page (pass the cursor straight back)

```bash
curl "http://127.0.0.1:8000/products?limit=5&cursor=eyJjcmVhdGVkX2F0IjogIjIwMjYtMDYtMjJUMTc6NTk6MDIuMTAyMzQ1KzAwOjAwIiwgImlkIjogIjNkNTk5..."
```

The client never needs to know what's inside the cursor — just copy
`next_cursor` from the previous response into the `cursor` query
parameter for the next request. When `next_cursor` is `null` (and
`has_more` is `false`), you've reached the end of the catalog.

### Filter by category

```bash
curl "http://127.0.0.1:8000/products?category=Electronics&limit=10"
```

### Filter by category AND paginate

```bash
curl "http://127.0.0.1:8000/products?category=Electronics&limit=10&cursor=<next_cursor from previous response>"
```

---

## Design Decisions

**UUID primary keys instead of auto-increment integers.** UUIDs don't
leak information (a sequential integer id tells a client roughly how
many rows exist and lets them enumerate every product by counting up).
They're also collision-free if data ever needs to be merged from
multiple sources.

**`Numeric` for price, not `Float`.** Floating point binary
representation cannot exactly represent most decimal fractions (the
classic `0.1 + 0.2 != 0.3` problem). `Numeric(10, 2)` maps to PostgreSQL's
exact decimal type, which is the correct choice for any currency value.

**Timezone-aware timestamps everywhere.** `created_at`/`updated_at` use
`DateTime(timezone=True)`, and the seed script generates UTC-aware
datetimes. Mixing naive and aware datetimes is a very common, very
subtle source of bugs in systems that later need to support users in
different timezones — better to be explicit from day one.

**`server_default=func.now()` / `onupdate=func.now()`.** Timestamps are
set by the database itself, not by application code. This guarantees
consistency even if multiple app instances (with slightly different
clocks) are writing to the database concurrently, and means
`updated_at` can never be forgotten by a future developer adding a new
code path that updates a product.

**Pydantic schemas separate from SQLAlchemy models.** `ProductOut` in
`schemas.py` is intentionally a different class from `Product` in
`models.py`. This means the public API response shape is decoupled from
the internal database schema — you could rename a database column or add
an internal-only column without it ever appearing in API responses.

**Opaque, encoded cursors.** The cursor is a base64-encoded JSON blob,
not a raw `?created_at=...&id=...` pair in the URL. Clients are expected
to treat it as a black box. This means the internal cursor format can
change later (e.g. to include more fields) without breaking existing API
consumers, as long as they keep passing back whatever string they were
given.

**The "fetch limit+1" trick for `has_more`.** Rather than running a
separate `COUNT(*)` query to determine whether more pages exist (which
would be a slow full-table scan against ~200,000 rows on every single
request), the query simply asks for one row more than `limit`. If that
extra row comes back, we know there's a next page; we then trim it off
before returning `items` to the client.

---

## Why Cursor Pagination Instead of OFFSET

This is the central technical decision of the assignment. The full
reasoning is also written as comments directly above
`get_products_page()` in `app/crud.py`, since that's the most useful
place to find it while reading the code — but here is the complete
explanation:

### The problem with OFFSET pagination

A typical "page-number" API looks like:
```sql
SELECT * FROM products ORDER BY created_at DESC LIMIT 20 OFFSET 40;
```
This says "skip the first 40 matching rows, then give me the next 20."

**Correctness problem.** OFFSET counts *positions* in the result set, not
specific rows. If a new product is inserted while a user is browsing
(sorted newest-first), every existing row shifts down by one position.
Concretely:

1. User loads page 1 (rows 1–20). They see product ranked #1 through #20.
2. While they're reading, another user adds a new product. It becomes
   the new #1, and everything else shifts down by one.
3. User loads page 2 with `OFFSET 20`. But "position 21" is now a
   *different* product than it would have been a moment ago — the
   product that used to be #20 has shifted into position 21, so the user
   sees it again (a duplicate), AND the product that used to be #21 has
   shifted to position 22, so the user will only see it if they keep
   paging — but if a few more inserts happen, it's possible to skip rows
   permanently.

For a feed of ~200,000 actively-updated products, this isn't a rare edge
case — it's the *normal* case for any real, multi-user browsing session.

**Performance problem.** `OFFSET 100000` still forces PostgreSQL to walk
through (and discard) the first 100,000 matching rows on every request,
even with a perfect index on the sort column. Cost grows roughly linearly
with how deep a user has paged — page 5,000 is far slower than page 1.

### How keyset (cursor) pagination fixes both problems

Instead of "skip N rows", the client says "give me rows that come after
the specific row I last saw":

```sql
SELECT * FROM products
WHERE (created_at, id) < (:cursor_created_at, :cursor_id)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

- **Correctness:** The `WHERE` clause is anchored to the *actual values*
  of a specific row, not a row count. Inserting a new product anywhere
  in the table cannot change what "rows older than this cursor" means.
  A new product is either newer than the cursor (so it appears in
  positions the user has already scrolled past, and they'll simply see
  it next time they refresh from the top) or it has no effect on the
  cursor's query at all. Either way: **no duplicates, no skipped rows**,
  no matter how much data changes mid-browse.

- **Performance:** This is a direct index range scan (using the
  composite index on `(created_at, id)` — see below), not a "count and
  skip." Postgres jumps straight to the right place in the index. Page 1
  and page 10,000 cost roughly the same.

### Why the cursor uses TWO columns, not just `created_at`

`created_at` alone is not guaranteed to be unique — two products could
plausibly be inserted in the same database transaction or the same
microsecond (this can actually happen during the bulk seed script).
If the cursor only tracked `created_at`, rows sharing a timestamp could
be skipped or duplicated at page boundaries. Pairing `created_at` with
the (always-unique) `id` as a tiebreaker, and comparing them together as
a SQL row value `(created_at, id) < (cursor_created_at, cursor_id)`,
guarantees a strict total ordering with no ties — the comparison always
makes forward progress.

---

## Database Indexing

Two composite indexes are defined on `products` (see `app/models.py`):

### 1. `idx_products_created_at_id` on `(created_at DESC, id DESC)`

Supports the main, unfiltered feed query:
```sql
ORDER BY created_at DESC, id DESC
WHERE (created_at, id) < (:cursor_created_at, :cursor_id)
```
A composite index whose column order matches the `ORDER BY` exactly lets
PostgreSQL retrieve rows already in the correct order directly from the
index (an "index scan"), avoiding a separate, expensive in-memory sort
step that would otherwise show up as a `Sort` node in
`EXPLAIN ANALYZE` output.

### 2. `idx_products_category_created_at_id` on `(category, created_at DESC, id DESC)`

Supports the category-filtered feed:
```sql
WHERE category = :category
ORDER BY created_at DESC, id DESC
```
Putting `category` as the **first** column means PostgreSQL can use this
one index to satisfy the `WHERE category = ...` filter *and* return
matching rows already sorted by `created_at DESC, id DESC` — both the
filtering and the ordering are solved by a single index scan, with no
extra sort step. This index is also usable for any future query that
just filters by category without caring about order, since `category`
being the leading column makes the index applicable on its own.

### How to verify this in practice

After seeding, you can confirm both indexes are actually being used:
```sql
EXPLAIN ANALYZE
SELECT * FROM products
ORDER BY created_at DESC, id DESC
LIMIT 20;

EXPLAIN ANALYZE
SELECT * FROM products
WHERE category = 'Electronics'
ORDER BY created_at DESC, id DESC
LIMIT 20;
```
You should see `Index Scan using idx_products_...` in the query plan
rather than `Seq Scan` (sequential scan of the whole table).

---

## Deploying on Render

These steps assume your code is pushed to a GitHub repository.

### Option A: One-click Blueprint deploy (uses `render.yaml`)

1. Push this `backend/` project (with `render.yaml` at its root) to
   GitHub.
2. Go to https://dashboard.render.com/blueprints
3. Click **New Blueprint Instance**, then select your repository.
4. Render reads `render.yaml` and shows you the `product-catalog-api`
   service it's about to create. Click **Apply**.
5. You'll be prompted to fill in the `DATABASE_URL` secret (because
   `render.yaml` marks it `sync: false`, meaning "don't store this value
   in the YAML — ask for it"). Paste in your Neon (or other PostgreSQL)
   connection string here.
6. Click **Create Web Service** / **Apply**. Render will:
   - Run `pip install -r requirements.txt` (the build step)
   - Start the app with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Poll `/health` to confirm the deploy is healthy before routing
     traffic to it

7. Once live, your API is reachable at something like:
   `https://product-catalog-api.onrender.com`

### Option B: Manual setup via the dashboard (no render.yaml needed)

1. Go to https://dashboard.render.com → **New** → **Web Service**.
2. Connect your GitHub repo.
3. Set:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/health`
4. Under **Environment**, add `DATABASE_URL` with your PostgreSQL
   connection string (and optionally `ALLOWED_ORIGINS`).
5. Click **Create Web Service**.

### After deploying: create tables and seed data

Render's free web service plan doesn't give you a persistent shell by
default, so the simplest approach is to run the one-time setup scripts
**from your own machine**, pointed at the same `DATABASE_URL` your
Render service uses (this works identically whether that database is
Neon, Render's own managed Postgres, or anything else reachable over the
internet):

```bash
# Locally, with DATABASE_URL in your .env set to the SAME database
# your deployed Render service uses:
python -m scripts.create_tables
python -m scripts.seed
```

Alternatively, if you're on a Render paid plan with shell access, you
can run the same two commands directly from the Render shell.

---

## Setting Up Neon PostgreSQL

[Neon](https://neon.tech) is a serverless, managed PostgreSQL provider
with a generous free tier — a good fit for this project since it
requires no local database installation and works the same way Render
does (just another `DATABASE_URL`).

### Steps

1. Go to https://neon.tech and sign up (GitHub/Google/email).
2. Click **Create a project**. Choose:
   - A project name (e.g. `product-catalog`)
   - A Postgres version (any recent default is fine)
   - A database name (e.g. `productdb`)
   - A region close to where your Render service will run
3. Click **Create project**. Neon immediately shows a connection string
   that looks like:
   ```
   postgresql://alex:AbC123dEf@ep-cool-darkness-a1b2c3d4.us-east-2.aws.neon.tech/productdb?sslmode=require
   ```
4. Copy that connection string into your `.env` file (locally) and into
   the `DATABASE_URL` environment variable on Render (when deploying).

### Pooled vs. unpooled connection strings

Neon's **Connect** modal offers two variants:
- **Pooled** (hostname contains `-pooler`) — routes through PgBouncer,
  supports many more concurrent connections. **Use this for the running
  API service** (it will hold a connection pool open and serve many
  concurrent requests).
- **Unpooled / direct** (no `-pooler` in the hostname) — a direct
  connection. **Use this for `scripts/seed.py` and
  `scripts/create_tables.py`.** PgBouncer's transaction-pooling mode can
  interact poorly with long-running bulk operations and some session-
  level features, so the one-time setup/seed scripts are safest run
  against the direct/unpooled connection string.

In short: API service → pooled URL. One-off scripts → unpooled URL. Both
point at the same underlying database, so data created by one is
immediately visible to the other.

### Important: `sslmode=require`

Neon requires SSL for all connections. Make sure `?sslmode=require` is
present at the end of your connection string (Neon includes it by
default when you copy the string from their dashboard — don't remove
it).

---

## Future Improvements

Given more time, these would be the next things worth adding:

- **Alembic migrations.** Right now, `scripts/create_tables.py` uses
  `Base.metadata.create_all()`, which is fine for a single, simple table
  that won't change. A real production system would use
  [Alembic](https://alembic.sqlalchemy.org/) so every schema change is
  written as a reviewable, reversible migration file instead of relying
  on SQLAlchemy to infer the current schema from the models.

- **Full-text search.** Category filtering is supported, but searching
  products by name (e.g. "find all products containing 'wireless'")
  would benefit from PostgreSQL's full-text search (`tsvector` +
  a GIN index) or an external search engine for fuzzier matching.

- **Rate limiting.** The API has no rate limiting yet. A production
  deployment would add per-IP or per-API-key rate limits (e.g. via
  `slowapi` or an API gateway) to protect against abuse.

- **Caching the first page.** The first page of the unfiltered feed
  (`GET /products` with no cursor) is requested far more often than deep
  pages. Caching it for a few seconds (e.g. in Redis) would reduce load
  on the database without affecting pagination correctness, since it's
  only ever the *entry point* into a cursor chain, not a page deep in
  someone's browsing session.

- **Async SQLAlchemy.** This project uses SQLAlchemy's synchronous API
  for simplicity and easier debugging (which matters for a project meant
  to be explained clearly in an interview). A high-throughput production
  system might switch to SQLAlchemy's async engine + `asyncpg` so a slow
  database query doesn't block the whole worker process.

- **Multi-field sorting.** Currently the feed only sorts by
  `created_at DESC, id DESC`. Supporting "sort by price" or "sort by
  name" with correct keyset pagination would require a separate
  composite index per sort option, and a more general cursor encoding
  that records which sort mode produced it.

- **Automated tests.** A `tests/` directory with pytest tests covering
  cursor correctness (e.g. "inserting a new product mid-pagination does
  not produce duplicates") would give strong confidence the pagination
  logic stays correct as the code evolves.
