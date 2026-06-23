"""
database.py
------------
Sets up the SQLAlchemy engine, session factory, and declarative base.

All database configuration comes from environment variables (never hardcoded),
so the same code works locally, in CI, and on Render/Neon in production.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

# Load variables from a local .env file if present.
# In production (Render), environment variables are injected directly by the
# platform, so load_dotenv() simply does nothing there — it's safe either way.
load_dotenv()

# The database connection string, e.g.:
# postgresql://user:password@host:5432/dbname
# For Neon/Render, this is typically provided as a single DATABASE_URL secret.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Copy .env.example to .env and fill in your database connection string."
    )

# create_engine builds the connection pool used by every request.
#
# pool_pre_ping=True makes SQLAlchemy test each connection with a lightweight
# query before handing it to a request. This avoids "server closed the
# connection unexpectedly" errors that happen when a managed Postgres
# provider (like Neon, which can suspend idle connections) silently drops
# an idle connection from the pool.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# SessionLocal is a factory for database sessions. Each incoming request
# gets its own session (see get_db() dependency below), which keeps requests
# isolated from one another.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the class that all ORM models (see models.py) inherit from.
# SQLAlchemy uses this to know which Python classes map to which DB tables.
#
# This uses SQLAlchemy 2.0's preferred `class Base(DeclarativeBase)` style
# (superseding the older `Base = declarative_base()` function call), which
# integrates better with type checkers and IDEs.
class Base(DeclarativeBase):
    pass


def get_db():
    """
    FastAPI dependency that provides a database session to route handlers.

    Using "yield" here means:
    1. A new session is created when a request comes in.
    2. The session is handed to the route function.
    3. After the route function finishes (success OR error), the `finally`
       block guarantees the session is closed and the connection is
       returned to the pool.

    This pattern avoids leaking connections, which is critical when serving
    many concurrent requests against a connection-limited database like
    Neon's free tier.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
