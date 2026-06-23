"""
models.py
---------
SQLAlchemy ORM models. This file defines the actual database schema in
Python — SQLAlchemy turns these classes into PostgreSQL tables.

Only one table is needed for this assignment: Product.
"""

import uuid
from sqlalchemy import Column, String, Numeric, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class Product(Base):
    """
    Represents a single product in the catalog.

    Column choices, explained:

    - id: UUID instead of an auto-incrementing integer. UUIDs are
      non-sequential and safe to expose publicly (a client can't guess
      "the next id" or infer how many products exist by probing ids).
      They also make it trivial to merge data from multiple sources later
      without id collisions.

    - created_at / updated_at: stored with timezone awareness
      (DateTime(timezone=True)). Mixing naive and aware datetimes is a
      classic source of subtle bugs once an app has users/servers in
      different timezones, so we make every timestamp explicitly UTC-aware
      from day one.

    - price: Numeric (maps to PostgreSQL's NUMERIC/DECIMAL), not Float.
      Floating point types lose precision for currency values (e.g.
      0.1 + 0.2 != 0.3 in binary floating point). Numeric stores exact
      decimal values, which is what you want for money.
    """

    __tablename__ = "products"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),  # let Postgres generate it too, as a safety net
    )
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),  # DB sets this automatically on INSERT
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # DB/SQLAlchemy refreshes this automatically on UPDATE
        nullable=False,
    )

    # -------------------------------------------------------------------
    # INDEXES — these are the backbone of fast pagination and filtering.
    # See the README's "Database Optimization" section for the full
    # reasoning, but in short:
    #
    # 1. idx_products_created_at_id
    #    A composite index on (created_at DESC, id DESC).
    #    Our main feed query is:
    #         ORDER BY created_at DESC, id DESC
    #         WHERE (created_at, id) < (:cursor_created_at, :cursor_id)
    #    A composite index matching the exact ORDER BY columns and
    #    direction lets Postgres walk the index directly in sorted order
    #    instead of pulling all matching rows into memory and sorting them
    #    (an expensive "sort" step you'd see in EXPLAIN ANALYZE otherwise).
    #
    #    Note: PostgreSQL CAN satisfy a DESC, DESC ordering using a
    #    plain ascending index by scanning it backwards, so this would
    #    still work without the explicit .desc() below. We declare it
    #    explicitly anyway so the index's on-disk order matches the
    #    query's ORDER BY exactly and unambiguously — this is the
    #    standard recommended practice for keyset pagination indexes and
    #    avoids relying on the planner's backward-scan optimization.
    #
    # 2. idx_products_category_created_at_id
    #    A composite index on (category, created_at DESC, id DESC).
    #    This supports the category-filtered feed:
    #         WHERE category = :category
    #         ORDER BY created_at DESC, id DESC
    #    Postgres can use this single index to both filter by category AND
    #    return rows already sorted in the order the API needs — no
    #    separate sort step required. Putting category FIRST in the index
    #    means it is also usable for plain "WHERE category = X" queries
    #    without the ordering, which keeps this one index broadly useful.
    # -------------------------------------------------------------------
    __table_args__ = (
        Index(
            "idx_products_created_at_id",
            created_at.desc(),
            id.desc(),
        ),
        Index(
            "idx_products_category_created_at_id",
            category,
            created_at.desc(),
            id.desc(),
        ),
    )

    def __repr__(self):
        return f"<Product id={self.id} name={self.name!r} category={self.category!r}>"
