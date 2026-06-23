"""
scripts/seed.py
----------------
Generates ~200,000 realistic fake products and inserts them into the
`products` table using EFFICIENT BULK INSERTION.

Run from the backend/ directory with:
    python -m scripts.seed

------------------------------------------------------------------------
WHY BULK INSERTION INSTEAD OF ROW-BY-ROW
------------------------------------------------------------------------
Inserting row-by-row (one INSERT statement + one round trip + one commit
per product) for 200,000 products would mean:
  - 200,000 separate network round trips to the database.
  - 200,000 separate transaction commits (each one forces a disk flush
    in Postgres by default).
  - The SQLAlchemy ORM's per-object overhead (change tracking, identity
    map bookkeeping) paid 200,000 times over.

On a typical setup this would take many minutes to hours and would put
real, unnecessary load on a hosted free-tier database like Neon.

Instead, this script:
  1. Builds product rows in memory in BATCHES (default 5,000 at a time).
  2. Uses SQLAlchemy Core's `Table.insert()` executed via
     `connection.execute(insert_stmt, list_of_dicts)`, which compiles to
     ONE multi-row INSERT statement per batch (executemany-style), not
     one statement per row.
  3. Commits once per batch, not once per row — far fewer round trips and
     disk flushes overall.

This brings total insert time for 200,000 rows down to roughly tens of
seconds on a typical hosted Postgres instance, instead of minutes/hours.
"""

import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from faker import Faker
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Allow running this script directly (`python -m scripts.seed`) from the
# backend/ directory by making sure the project root is importable.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Product  # noqa: E402  (import after sys.path tweak, intentionally)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and configure it.")

# --- Configuration -------------------------------------------------------
TOTAL_PRODUCTS = int(os.getenv("SEED_TOTAL_PRODUCTS", 200_000))
BATCH_SIZE = int(os.getenv("SEED_BATCH_SIZE", 5_000))

CATEGORIES = [
    "Electronics",
    "Fashion",
    "Books",
    "Home",
    "Sports",
    "Beauty",
    "Automotive",
]

# Category-appropriate noun pools so generated names read as believable
# product names (e.g. "Wireless Bluetooth Headphones") rather than random
# generic words. Faker's catch_phrase()/word() alone tends to produce
# names that don't look like real product listings.
CATEGORY_NOUNS = {
    "Electronics": ["Headphones", "Laptop", "Smartphone", "Monitor", "Speaker", "Charger", "Camera", "Tablet", "Router", "Smartwatch"],
    "Fashion": ["T-Shirt", "Jacket", "Jeans", "Sneakers", "Dress", "Handbag", "Scarf", "Hoodie", "Sunglasses", "Belt"],
    "Books": ["Novel", "Cookbook", "Biography", "Textbook", "Comic", "Journal", "Guidebook", "Anthology", "Memoir", "Encyclopedia"],
    "Home": ["Blender", "Sofa", "Lamp", "Curtains", "Cookware Set", "Mattress", "Vacuum Cleaner", "Bookshelf", "Dinner Set", "Rug"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Running Shoes", "Tennis Racket", "Cycling Helmet", "Football", "Treadmill", "Gym Bag", "Resistance Bands", "Water Bottle"],
    "Beauty": ["Face Cream", "Lipstick", "Shampoo", "Perfume", "Serum", "Sunscreen", "Hair Dryer", "Makeup Kit", "Nail Polish", "Face Mask"],
    "Automotive": ["Car Battery", "Tire", "Dash Camera", "Engine Oil", "Car Cover", "Seat Cushion", "Jump Starter", "Air Freshener", "Roof Rack", "Wiper Blades"],
}

CATEGORY_PRICE_RANGES = {
    # (min_price, max_price) — roughly realistic ranges per category, in
    # whatever currency unit; kept simple since the exact currency isn't
    # specified by the assignment.
    "Electronics": (15, 2500),
    "Fashion": (8, 300),
    "Books": (5, 80),
    "Home": (10, 1200),
    "Sports": (8, 600),
    "Beauty": (5, 150),
    "Automotive": (10, 900),
}

fake = Faker()


def generate_product_row(created_at: datetime) -> dict:
    """
    Build a single product as a plain dict (not an ORM object — ORM
    objects carry tracking overhead we don't need for a bulk insert).
    """
    category = random.choice(CATEGORIES)
    noun = random.choice(CATEGORY_NOUNS[category])
    brandish = fake.company().split(" ")[0]  # short, brand-like word
    adjective = fake.word().capitalize()
    name = f"{brandish} {adjective} {noun}"[:255]

    min_price, max_price = CATEGORY_PRICE_RANGES[category]
    price = round(random.uniform(min_price, max_price), 2)

    return {
        "id": uuid.uuid4(),
        "name": name,
        "category": category,
        "price": price,
        "created_at": created_at,
        # On first insert, updated_at starts equal to created_at.
        "updated_at": created_at,
    }


def random_timestamp_within_last_n_days(days: int = 365) -> datetime:
    """
    Spread products across the last `days` days so the feed has a
    realistic, varied "newest first" ordering instead of every product
    sharing the exact same timestamp.
    """
    now = datetime.now(timezone.utc)
    seconds_back = random.randint(0, days * 24 * 60 * 60)
    return now - timedelta(seconds=seconds_back)


def seed():
    engine = create_engine(DATABASE_URL)

    print(f"Seeding {TOTAL_PRODUCTS:,} products in batches of {BATCH_SIZE:,}...")

    inserted = 0
    table = Product.__table__  # SQLAlchemy Core Table object for bulk insert

    # One connection, reused for every batch — avoids reconnect overhead
    # per batch. Each batch is committed as its own transaction so that if
    # something fails partway through a huge run, earlier batches are
    # already durably saved rather than the whole job rolling back.
    with engine.connect() as conn:
        while inserted < TOTAL_PRODUCTS:
            batch_count = min(BATCH_SIZE, TOTAL_PRODUCTS - inserted)

            # Build this batch fully in memory first...
            rows = [
                generate_product_row(random_timestamp_within_last_n_days())
                for _ in range(batch_count)
            ]

            # ...then send it as ONE multi-row INSERT statement.
            # Passing a list of dicts to conn.execute() with a Core insert()
            # construct makes SQLAlchemy use executemany under the hood,
            # which most DBAPI drivers (including psycopg2) batch
            # efficiently into a single round trip per batch.
            conn.execute(table.insert(), rows)
            conn.commit()

            inserted += batch_count
            print(f"  Inserted {inserted:,} / {TOTAL_PRODUCTS:,}")

    print("Done. Seeding complete.")


if __name__ == "__main__":
    seed()
