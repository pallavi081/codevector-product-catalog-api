"""
scripts/create_tables.py
-------------------------
Creates all tables defined in app/models.py (just `products` for this
project), including the indexes declared on the model.

Run once before seeding:
    python -m scripts.create_tables

This uses SQLAlchemy's Base.metadata.create_all(), which is fine for a
project of this size with a single, simple table. For a larger production
system that evolves over time, this would typically be replaced with a
proper migration tool (Alembic) so schema changes are versioned — see the
README's "Future Improvements" section.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine  # noqa: E402
from app import models  # noqa: E402,F401  (import so the Product model registers with Base)


def create_tables():
    print("Creating tables (if they do not already exist)...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables and indexes are ready.")


if __name__ == "__main__":
    create_tables()
