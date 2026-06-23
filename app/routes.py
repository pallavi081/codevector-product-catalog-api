"""
routes.py
---------
API endpoint definitions. Route handlers stay thin: they parse/validate
input (mostly handled by FastAPI + Pydantic already), call into crud.py
for the actual database logic, and shape the response.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas import HealthResponse, PaginatedProductsResponse, ProductOut

router = APIRouter()

# Categories accepted by the seed script / expected in the catalog.
# Used only for documentation in the OpenAPI schema (Swagger UI) — we
# deliberately do NOT hard-validate `category` against this list in the
# query parameter itself, so the API still works correctly if new
# categories are added to the catalog later without a code change.
KNOWN_CATEGORIES = [
    "Electronics",
    "Fashion",
    "Books",
    "Home",
    "Sports",
    "Beauty",
    "Automotive",
]


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check(db: Session = Depends(get_db)):
    """
    Basic health check endpoint.

    Confirms two things:
    1. The API process is up and able to handle a request.
    2. The database connection actually works (not just that the process
       is running) — this is what makes this check useful for deployment
       platforms like Render, which poll a health endpoint to decide if a
       new deploy is healthy before routing traffic to it.
    """
    try:
        crud.check_database_connection(db)
        db_status = "connected"
    except OperationalError:
        # Don't crash the health endpoint itself if the DB is down —
        # report it clearly instead so monitoring tools can alert on it.
        db_status = "unavailable"

    return HealthResponse(status="ok", database=db_status)


@router.get("/products", response_model=PaginatedProductsResponse, tags=["products"])
def list_products(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of products to return (1-100).",
    ),
    cursor: Optional[str] = Query(
        default=None,
        description=(
            "Opaque pagination cursor from a previous response's "
            "next_cursor field. Omit this to get the first page."
        ),
    ),
    category: Optional[str] = Query(
        default=None,
        description=f"Optional category filter. Known categories: {', '.join(KNOWN_CATEGORIES)}.",
    ),
    db: Session = Depends(get_db),
):
    """
    GET /products

    Returns products newest-first, using cursor (keyset) pagination.

    Examples:
      First page:               GET /products?limit=20
      Next page:                GET /products?limit=20&cursor=<next_cursor from previous response>
      Filtered by category:     GET /products?category=Electronics&limit=20
      Filtered + paginated:     GET /products?category=Electronics&limit=20&cursor=<...>

    See crud.py's module docstring for the full explanation of why this
    uses cursor pagination instead of OFFSET/page-number pagination.
    """
    try:
        items, next_cursor, has_more = crud.get_products_page(
            db=db, limit=limit, cursor=cursor, category=category
        )
    except ValueError:
        # Raised by crud.decode_cursor() when the cursor is malformed —
        # surface it as a client error, not a 500.
        raise HTTPException(status_code=400, detail="Invalid cursor parameter")

    return PaginatedProductsResponse(
        items=[ProductOut.model_validate(p) for p in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )
