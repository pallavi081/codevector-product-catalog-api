"""
crud.py
-------
Database query logic, kept separate from the route handlers in routes.py.
This is where the cursor (keyset) pagination is implemented.

------------------------------------------------------------------------
WHY CURSOR PAGINATION INSTEAD OF OFFSET PAGINATION
------------------------------------------------------------------------
This is the central design decision of the assignment, so it's explained
here in detail (and summarized again in the README).

OFFSET pagination (`LIMIT 20 OFFSET 40`) has two serious problems at scale:

1. CORRECTNESS PROBLEM — "skipped or duplicated rows" when data changes.
   OFFSET works by counting rows from the start of the result set and
   skipping that many. If a new product is inserted while a user is
   browsing (sorted newest-first), every row after it shifts down by one
   position. On page 2, OFFSET 20 now points to a DIFFERENT row than it
   did a moment ago — the user can see the same product twice (it shifted
   into a position they already viewed) or never see a product at all (it
   shifted past a page boundary they already passed). For a feed of
   ~200,000 actively-updated products, this isn't a rare edge case, it's
   the normal case during any real browsing session.

2. PERFORMANCE PROBLEM — OFFSET gets slower the deeper you page.
   `OFFSET 100000` still forces Postgres to scan and discard the first
   100,000 matching rows on every single request, even though an index
   exists. The cost grows linearly with how deep the user has paged.

CURSOR (KEYSET) pagination solves both problems:

- Instead of saying "skip N rows", the client says "give me rows that
  come after the last row I saw" by sending back the (created_at, id) of
  that last row as a cursor.
- The query becomes:
      WHERE (created_at, id) < (:cursor_created_at, :cursor_id)
      ORDER BY created_at DESC, id DESC
      LIMIT :limit
- This is a direct index lookup (see models.py for the composite index),
  not a "count and skip". Its speed is roughly constant no matter how deep
  the user pages — page 1 and page 5,000 cost about the same.
- Because the WHERE clause is anchored to a specific row's actual values
  rather than a row count, inserting new products anywhere in the table
  cannot shift the meaning of an existing cursor. A new product is either
  newer than the cursor (so it appears further up, where the user has
  already finished scrolling, and is simply seen on their next full
  refresh) or it doesn't affect the cursor's position at all. Either way,
  rows already seen are never re-shown, and rows not yet seen are never
  skipped.

Why we use a COMPOUND key (created_at, id) and not just created_at:
created_at alone is not guaranteed unique — with 200,000 seeded rows, it's
entirely possible for two products to share the same microsecond
timestamp (especially if seeded in a tight loop). Pairing created_at with
the (unique) id as a tiebreaker guarantees a strict, total ordering, so
the "< cursor" comparison always advances and never gets stuck.
"""

import base64
import json
import uuid
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models import Product


def encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    """
    Turn a (created_at, id) pair into an opaque, URL-safe string.

    Cursors are deliberately opaque to clients — they should treat it as a
    black box and just pass it back verbatim. Encoding it (rather than
    exposing raw "created_at=...&id=..." query params) avoids clients
    depending on the internal format, so we're free to change how cursors
    are built later without breaking API consumers.
    """
    raw = json.dumps({"created_at": created_at.isoformat(), "id": str(id_)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> Tuple[datetime, uuid.UUID]:
    """
    Reverse of encode_cursor. Raises ValueError on a malformed cursor,
    which the route layer turns into a clean 400 response.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        created_at = datetime.fromisoformat(data["created_at"])
        id_ = uuid.UUID(data["id"])
        return created_at, id_
    except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid or corrupted cursor") from exc


def get_products_page(
    db: Session,
    limit: int,
    cursor: Optional[str] = None,
    category: Optional[str] = None,
):
    """
    Fetch one page of products, newest first, optionally filtered by
    category, using keyset pagination.

    Returns a tuple: (list_of_products, next_cursor_or_None)
    """
    query = db.query(Product)

    # Optional category filter. This is applied BEFORE the cursor filter
    # and ordering, and the (category, created_at, id) composite index
    # defined in models.py lets Postgres satisfy both the WHERE and the
    # ORDER BY from a single index scan.
    if category:
        query = query.filter(Product.category == category)

    # Cursor filter: only fetch rows "older" than the last row the client
    # already saw, using the same ordering as the ORDER BY below.
    #
    # tuple_(...) builds a row-wise comparison:
    #   (created_at, id) < (cursor_created_at, cursor_id)
    # This is the standard SQL "row value" comparison technique for
    # multi-column keyset pagination — it correctly handles the tie-breaker
    # case where two rows share the same created_at.
    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        query = query.filter(
            tuple_(Product.created_at, Product.id) < (cursor_created_at, cursor_id)
        )

    # Always sort newest first, with id DESC as a tiebreaker for rows that
    # share a created_at timestamp. This MUST match the column order of
    # the cursor comparison above and the composite index, or Postgres
    # cannot use the index to satisfy the ORDER BY.
    query = query.order_by(Product.created_at.desc(), Product.id.desc())

    # Fetch one extra row beyond what we'll return. If we get back
    # limit + 1 rows, we know there's at least one more page, so we set
    # next_cursor. If we get back <= limit rows, this is the last page.
    # This "fetch limit+1" trick avoids a separate COUNT(*) query just to
    # know whether more data exists.
    rows = query.limit(limit + 1).all()

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return items, next_cursor, has_more


def check_database_connection(db: Session) -> bool:
    """Used by the /health endpoint to confirm the DB is reachable."""
    db.execute(Product.__table__.select().limit(1))
    return True
