"""
main.py
-------
FastAPI application entrypoint. This is what Uvicorn runs:
    uvicorn app.main:app
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router

app = FastAPI(
    title="Product Catalog API",
    description=(
        "Backend for browsing ~200,000 products with category filtering "
        "and cursor-based (keyset) pagination that stays correct even "
        "while products are being added or updated concurrently."
    ),
    version="1.0.0",
)

# CORS is wide-open here for assignment/demo purposes (so the API can be
# called from any frontend during development/grading without extra
# configuration). In a real production system, ALLOWED_ORIGINS would be
# restricted to your actual frontend's domain(s) via an environment
# variable rather than "*".
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[allowed_origins] if allowed_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All actual routes (/products, /health) live in routes.py and are
# attached to the app here, keeping main.py focused purely on app setup.
app.include_router(router)


@app.get("/", tags=["root"])
def root():
    """Simple landing route so hitting the bare URL doesn't just 404."""
    return {
        "message": "Product Catalog API is running.",
        "docs": "/docs",
        "health": "/health",
    }
